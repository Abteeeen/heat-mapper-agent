from unittest.mock import MagicMock

from shadescout import pipeline
from shadescout.errors import GeocodingError
from shadescout.models import Coordinates, PropertyListing, VisionAnalysis


def test_build_postcard_text_with_weather(monkeypatch):
    monkeypatch.setattr(pipeline, "get_upcoming_hot_day", lambda coords: ("Saturday", 97))
    text = pipeline.build_postcard_text(10, Coordinates(30.0, -97.0))
    assert "10 hours" in text
    assert "Saturday" in text
    assert "97" in text


def test_build_postcard_text_without_weather(monkeypatch):
    monkeypatch.setattr(pipeline, "get_upcoming_hot_day", lambda coords: None)
    text = pipeline.build_postcard_text(6, Coordinates(30.0, -97.0))
    assert "6 hours" in text
    assert "louvered pergola" in text


def _make_prop(address="123 Main St"):
    return PropertyListing(formatted_address=address)


def test_process_property_qualified(monkeypatch):
    monkeypatch.setattr(pipeline, "get_upcoming_hot_day", lambda coords: None)

    geocoder = MagicMock()
    geocoder.geocode.return_value = Coordinates(30.0, -97.0)
    imagery = MagicMock()
    imagery.get_satellite_image_b64.return_value = "sat"
    imagery.get_street_view_image_b64.return_value = "street"
    vision = MagicMock()
    vision.analyze_property.return_value = VisionAnalysis(
        has_patio=True, already_covered=False, estimated_sun_hours=9
    )

    lead = pipeline.process_property(
        _make_prop(),
        geocoder=geocoder,
        imagery=imagery,
        vision=vision,
        save_images=False,
        image_dir=None,
    )

    assert lead is not None
    assert lead.property_address == "123 Main St"
    assert lead.sun_hours == 9
    assert lead.satellite_image_path is None


def test_process_property_uses_embedded_coordinates_and_skips_geocoding(monkeypatch):
    monkeypatch.setattr(pipeline, "get_upcoming_hot_day", lambda coords: None)

    geocoder = MagicMock()
    imagery = MagicMock()
    imagery.get_satellite_image_b64.return_value = "sat"
    imagery.get_street_view_image_b64.return_value = "street"
    vision = MagicMock()
    vision.analyze_property.return_value = VisionAnalysis(
        has_patio=True, already_covered=False, estimated_sun_hours=8
    )

    prop = PropertyListing(
        formatted_address="42 Coords Ave",
        coordinates=Coordinates(30.25, -97.78),
    )
    lead = pipeline.process_property(
        prop,
        geocoder=geocoder,
        imagery=imagery,
        vision=vision,
        save_images=False,
        image_dir=None,
    )

    assert lead is not None
    assert lead.coordinates == Coordinates(30.25, -97.78)
    geocoder.geocode.assert_not_called()


def test_process_property_disqualified_already_covered(monkeypatch):
    geocoder = MagicMock()
    geocoder.geocode.return_value = Coordinates(30.0, -97.0)
    imagery = MagicMock()
    imagery.get_satellite_image_b64.return_value = "sat"
    imagery.get_street_view_image_b64.return_value = "street"
    vision = MagicMock()
    vision.analyze_property.return_value = VisionAnalysis(
        has_patio=True, already_covered=True, estimated_sun_hours=4
    )

    lead = pipeline.process_property(
        _make_prop(),
        geocoder=geocoder,
        imagery=imagery,
        vision=vision,
        save_images=False,
        image_dir=None,
    )
    assert lead is None


def test_process_property_disqualified_no_patio(monkeypatch):
    geocoder = MagicMock()
    geocoder.geocode.return_value = Coordinates(30.0, -97.0)
    imagery = MagicMock()
    imagery.get_satellite_image_b64.return_value = "sat"
    imagery.get_street_view_image_b64.return_value = "street"
    vision = MagicMock()
    vision.analyze_property.return_value = VisionAnalysis(
        has_patio=False, already_covered=False, estimated_sun_hours=8
    )

    lead = pipeline.process_property(
        _make_prop(),
        geocoder=geocoder,
        imagery=imagery,
        vision=vision,
        save_images=False,
        image_dir=None,
    )
    assert lead is None


def test_run_skips_property_on_geocoding_error(monkeypatch):
    settings = MagicMock()
    settings.realty_provider = "rentcast"
    settings.rentcast_api_key = "k"
    settings.google_maps_api_key = "g"
    settings.openrouter_api_key = "o"
    settings.vision_model = "m"
    settings.request_timeout = 30
    settings.max_days_since_sale = 180

    realty_client = MagicMock()
    realty_client.fetch_recent_sales.return_value = [_make_prop("1 Bad St"), _make_prop("2 Good St")]
    monkeypatch.setattr(pipeline, "build_realty_client", lambda settings: realty_client)

    geocoder = MagicMock()
    geocoder.geocode.side_effect = [GeocodingError("boom"), Coordinates(30.0, -97.0)]
    monkeypatch.setattr(pipeline, "GeocodingClient", lambda *a, **k: geocoder)

    imagery = MagicMock()
    imagery.get_satellite_image_b64.return_value = "sat"
    imagery.get_street_view_image_b64.return_value = "street"
    monkeypatch.setattr(pipeline, "ImageryClient", lambda *a, **k: imagery)

    vision = MagicMock()
    vision.analyze_property.return_value = VisionAnalysis(
        has_patio=True, already_covered=False, estimated_sun_hours=7
    )
    monkeypatch.setattr(pipeline, "VisionClient", lambda *a, **k: vision)
    monkeypatch.setattr(pipeline, "get_upcoming_hot_day", lambda coords: None)

    leads = pipeline.run("78704", limit=10, settings=settings)

    assert len(leads) == 1
    assert leads[0].property_address == "2 Good St"
