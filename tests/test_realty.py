from datetime import datetime, timedelta, timezone

import pytest

from shadescout.clients import realty
from shadescout.errors import RealtyDataError


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")


@pytest.mark.parametrize(
    "location,expected",
    [
        ("78704", {"zipCode": "78704"}),
        ("Austin, TX", {"city": "Austin", "state": "TX"}),
        ("Austin", {"city": "Austin"}),
    ],
)
def test_location_params(location, expected):
    assert realty._location_params(location) == expected


def test_to_listings_filters_stale_sales_and_sorts_desc():
    records = [
        {"formattedAddress": "1 Old St", "lastSaleDate": _iso_days_ago(400)},
        {"formattedAddress": "2 Recent St", "lastSaleDate": _iso_days_ago(5)},
        {"formattedAddress": "3 Mid St", "lastSaleDate": _iso_days_ago(30)},
        {"formattedAddress": None},  # no address -> dropped
    ]
    listings = realty._to_listings(records, limit=10, max_days_since_sale=180)
    addresses = [l.formatted_address for l in listings]
    assert addresses == ["2 Recent St", "3 Mid St"]


def test_to_listings_respects_limit():
    records = [{"formattedAddress": f"{i} St", "lastSaleDate": _iso_days_ago(1)} for i in range(5)]
    listings = realty._to_listings(records, limit=2, max_days_since_sale=180)
    assert len(listings) == 2


def test_rentcast_client_success(monkeypatch):
    captured = {}

    def fake_request_json(method, url, *, error_cls, error_context, timeout, headers, params):
        captured["headers"] = headers
        captured["params"] = params
        return [{"formattedAddress": "123 Main St, Austin, TX 78704", "lastSaleDate": _iso_days_ago(10)}]

    monkeypatch.setattr(realty, "request_json", fake_request_json)

    client = realty.RentCastClient(api_key="fake-key")
    listings = client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)

    assert len(listings) == 1
    assert listings[0].formatted_address == "123 Main St, Austin, TX 78704"
    assert captured["headers"]["X-Api-Key"] == "fake-key"
    assert captured["params"]["zipCode"] == "78704"


def test_rentcast_client_bad_shape_raises(monkeypatch):
    monkeypatch.setattr(realty, "request_json", lambda *a, **k: {"unexpected": "shape"})
    client = realty.RentCastClient(api_key="fake-key")
    with pytest.raises(RealtyDataError):
        client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)


def test_build_realty_client_selects_provider():
    from shadescout.config import Settings

    settings = Settings(
        google_maps_api_key="g",
        openrouter_api_key="o",
        realty_provider="realtyapi",
        realtyapi_key="a",
        rentcast_api_key=None,
        rapidapi_key=None,
        vision_model="m",
        max_days_since_sale=180,
        request_timeout=30,
    )
    assert isinstance(realty.build_realty_client(settings), realty.RealtyAPIClient)

    settings2 = Settings(**{**settings.__dict__, "realty_provider": "rentcast", "rentcast_api_key": "r"})
    assert isinstance(realty.build_realty_client(settings2), realty.RentCastClient)

    settings3 = Settings(**{**settings.__dict__, "realty_provider": "rapidapi_realtymole", "rapidapi_key": "k"})
    assert isinstance(realty.build_realty_client(settings3), realty.RealtyMoleRapidAPIClient)


def test_realtyapi_client_success(monkeypatch):
    captured = {}

    def fake_request_json(method, url, *, error_cls, error_context, timeout, headers, params):
        captured["headers"] = headers
        captured["params"] = params
        return {"results": [{"formattedAddress": "9 Realtyapi Way, Austin, TX 78704", "soldDate": _iso_days_ago(3)}]}

    monkeypatch.setattr(realty, "request_json", fake_request_json)

    client = realty.RealtyAPIClient(api_key="fake-key")
    listings = client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)

    assert len(listings) == 1
    assert listings[0].formatted_address == "9 Realtyapi Way, Austin, TX 78704"
    assert captured["headers"]["x-realtyapi-key"] == "fake-key"
    assert captured["params"]["zipCode"] == "78704"


def test_realtyapi_client_handles_real_envelope_shape(monkeypatch):
    # Exact shape confirmed from a live call: a single-element array
    # wrapping an envelope object with the actual records under
    # "searchResults".
    def fake_request_json(*a, **k):
        return [
            {
                "source": "realtor.com",
                "total": 1,
                "nextPage": False,
                "resultCount": 1,
                "searchResults": [
                    {"formattedAddress": "5 Envelope Ct, Austin, TX 78704", "soldDate": _iso_days_ago(4)}
                ],
            }
        ]

    monkeypatch.setattr(realty, "request_json", fake_request_json)
    client = realty.RealtyAPIClient(api_key="fake-key")
    listings = client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)

    assert len(listings) == 1
    assert listings[0].formatted_address == "5 Envelope Ct, Austin, TX 78704"


def test_realtyapi_client_surfaces_error_disguised_as_empty_result(monkeypatch):
    # The exact response seen when the zipCode param was missing/wrong:
    # HTTP 200 with an embedded error message and an empty searchResults.
    def fake_request_json(*a, **k):
        return [
            {
                "message": "404: zipCode required for /search/byzip",
                "source": "realtor.com",
                "total": 0,
                "nextPage": False,
                "resultCount": 0,
                "searchResults": [],
            }
        ]

    monkeypatch.setattr(realty, "request_json", fake_request_json)
    client = realty.RealtyAPIClient(api_key="fake-key")
    with pytest.raises(RealtyDataError, match="zipCode required"):
        client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)


def test_realtyapi_client_rejects_non_zip_location():
    client = realty.RealtyAPIClient(api_key="fake-key")
    with pytest.raises(RealtyDataError, match="ZIP"):
        client.fetch_recent_sales("Austin, TX", limit=5, max_days_since_sale=180)


def test_realtyapi_client_handles_alternate_container_and_field_names(monkeypatch):
    def fake_request_json(*a, **k):
        return {"data": [{"full_address": "1 Alt Ln", "sold_date": _iso_days_ago(2), "sold_price": 500000}]}

    monkeypatch.setattr(realty, "request_json", fake_request_json)
    client = realty.RealtyAPIClient(api_key="fake-key")
    listings = client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)

    assert listings[0].formatted_address == "1 Alt Ln"
    assert listings[0].price == 500000


def test_realtyapi_client_unrecognizable_shape_raises(monkeypatch):
    monkeypatch.setattr(realty, "request_json", lambda *a, **k: {"unexpected": "shape"})
    client = realty.RealtyAPIClient(api_key="fake-key")
    with pytest.raises(RealtyDataError):
        client.fetch_recent_sales("78704", limit=5, max_days_since_sale=180)
