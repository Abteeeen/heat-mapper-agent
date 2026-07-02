import pytest

from shadescout.clients import geocoding
from shadescout.errors import GeocodingError


def test_geocode_success(monkeypatch):
    def fake_request_json(method, url, *, error_cls, error_context, timeout, params):
        assert params["address"] == "123 Main St"
        return {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 30.25, "lng": -97.75}}}],
        }

    monkeypatch.setattr(geocoding, "request_json", fake_request_json)
    client = geocoding.GeocodingClient(api_key="fake")
    coords = client.geocode("123 Main St")
    assert coords.lat == 30.25
    assert coords.lng == -97.75


def test_geocode_zero_results_raises(monkeypatch):
    monkeypatch.setattr(geocoding, "request_json", lambda *a, **k: {"status": "ZERO_RESULTS", "results": []})
    client = geocoding.GeocodingClient(api_key="fake")
    with pytest.raises(GeocodingError):
        client.geocode("nowhere")


def test_geocode_denied_raises(monkeypatch):
    monkeypatch.setattr(
        geocoding,
        "request_json",
        lambda *a, **k: {"status": "REQUEST_DENIED", "error_message": "bad key"},
    )
    client = geocoding.GeocodingClient(api_key="fake")
    with pytest.raises(GeocodingError, match="bad key"):
        client.geocode("123 Main St")
