"""Step 1: Lead generation — find recently-sold homes in a target area.

Three providers are supported, all producing the same ``PropertyListing``
shape so the rest of the pipeline doesn't care which one is active:

- ``realtyapi`` (default): realtyapi.io's Realtor endpoint. Free tier is
  250 requests/month and their signup does not ask for a credit card
  (RentCast's does, despite being marketed as free — that's why this is
  the default instead). The request shape (``zipCode`` param, response
  wrapped as ``[{"searchResults": [...], ...}]``) has been confirmed
  against a live call. The *record* field names (address/sale-date/price
  inside each ``searchResults`` entry) are still unverified against a
  non-empty result, so ``_to_listings_realtyapi`` stays defensive (tries
  several plausible field-name variants) — if it doesn't parse a real
  response, run with ``-v`` and adjust ``_ADDRESS_KEYS`` / ``_SALE_DATE_KEYS``
  / ``_PRICE_KEYS`` / ``_RECORDS_CONTAINER_KEYS`` to match what comes back.
- ``rentcast``: RentCast's native API (also the Realty Mole successor).
  Free tier, but their signup flow does ask for card details.
- ``rapidapi_realtymole``: the original RapidAPI "Realty Mole Property
  API", kept for teams with an existing RapidAPI subscription.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from shadescout.errors import RealtyDataError
from shadescout.http import request_json
from shadescout.models import Coordinates, PropertyListing

_ZIP_RE = re.compile(r"^\d{5}$")
_CITY_STATE_RE = re.compile(r"^([^,]+),\s*([A-Za-z]{2})$")


def _location_params(location: str) -> dict:
    """Turn a user-supplied location ("78704", "Austin, TX", "Austin") into
    the query params these APIs expect.
    """
    location = location.strip()
    if _ZIP_RE.match(location):
        return {"zipCode": location}
    match = _CITY_STATE_RE.match(location)
    if match:
        return {"city": match.group(1).strip(), "state": match.group(2).upper()}
    return {"city": location}


def _parse_sale_date(raw: dict) -> str | None:
    for key in ("lastSaleDate", "removedDate", "listedDate"):
        value = raw.get(key)
        if value:
            return value
    return None


def _days_since(iso_date: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).days


def _to_listings(records: list[dict], limit: int, max_days_since_sale: int) -> list[PropertyListing]:
    listings = []
    for record in records:
        address = record.get("formattedAddress")
        if not address:
            continue
        sale_date = _parse_sale_date(record)
        if sale_date is not None:
            age_days = _days_since(sale_date)
            if age_days is not None and age_days > max_days_since_sale:
                continue
        listings.append(
            PropertyListing(
                formatted_address=address,
                last_sale_date=sale_date,
                price=record.get("lastSalePrice") or record.get("price"),
                raw=record,
            )
        )

    def sort_key(listing: PropertyListing) -> str:
        return listing.last_sale_date or ""

    listings.sort(key=sort_key, reverse=True)
    return listings[:limit]


class RealtyDataClient(ABC):
    @abstractmethod
    def fetch_recent_sales(self, location: str, limit: int, max_days_since_sale: int) -> list[PropertyListing]:
        """Return up to ``limit`` recently-sold properties for ``location``."""


# realtyapi.io response shape, confirmed against live calls: GET /search/byzip
# wants a `zipCode` param and wraps results as `[{"searchResults": [...]}]`.
# Each record carries realtor.com-style fields: an `address` object
# ({line, city, state_code, postal_code, latitude, longitude}), plus
# `last_sold_date`, `last_sold_price`, `list_price`, `status`, `estimate`.
# The remaining alternate names are kept as fallbacks for other providers'
# spellings behind the same aggregator.
_ADDRESS_KEYS = ("formattedAddress", "full_address", "fullAddress", "address", "streetAddress", "location")
_SALE_DATE_KEYS = ("last_sold_date", "lastSaleDate", "soldDate", "sold_date", "closeDate", "close_date", "dateSold")
_PRICE_KEYS = ("last_sold_price", "lastSalePrice", "soldPrice", "sold_price", "list_price", "price", "closePrice")
_RECORDS_CONTAINER_KEYS = ("searchResults", "results", "properties", "listings", "data", "homes")


def _first(record: dict, keys: tuple[str, ...]):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _format_address(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [
            _first(value, ("line", "street", "streetAddress")),
            value.get("city"),
            _first(value, ("state_code", "state")),
            _first(value, ("postal_code", "zip", "zipcode")),
        ]
        parts = [str(p) for p in parts if p]
        return ", ".join(parts) if parts else None
    return None


def _extract_coords(record: dict) -> Coordinates | None:
    address = record.get("address")
    candidates = [address, record] if isinstance(address, dict) else [record]
    for candidate in candidates:
        lat = _first(candidate, ("latitude", "lat"))
        lng = _first(candidate, ("longitude", "lng", "lon"))
        if lat is not None and lng is not None:
            try:
                return Coordinates(lat=float(lat), lng=float(lng))
            except (TypeError, ValueError):
                continue
    return None


def _extract_records(data) -> list[dict]:
    # The API wraps results as a single-element array around an envelope
    # object: [{"searchResults": [...], ...}]. Unwrap that before looking
    # for a container key.
    candidates = data if isinstance(data, list) else [data]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in _RECORDS_CONTAINER_KEYS:
            value = candidate.get(key)
            if isinstance(value, list):
                if not value and candidate.get("message"):
                    # e.g. [{"message": "404: zipCode required for /search/byzip",
                    #        "searchResults": [], ...}] — an error disguised as an
                    #        empty result rather than a non-2xx status.
                    raise RealtyDataError(f"RealtyAPI /search/byzip returned an error: {candidate['message']}")
                return value

    # Fall back to treating the top-level list as the record list itself,
    # in case a different query shape skips the envelope wrapper.
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        return data

    shape = list(data.keys())[:10] if isinstance(data, dict) else type(data).__name__
    raise RealtyDataError(f"RealtyAPI response had no recognizable list of properties (shape: {shape})")


def _to_listings_realtyapi(records: list[dict], limit: int, max_days_since_sale: int) -> list[PropertyListing]:
    listings = []
    for record in records:
        address = _format_address(_first(record, _ADDRESS_KEYS))
        if not address:
            continue
        sale_date = _first(record, _SALE_DATE_KEYS)
        if sale_date is not None:
            age_days = _days_since(str(sale_date))
            if age_days is not None and age_days > max_days_since_sale:
                continue
        listings.append(
            PropertyListing(
                formatted_address=address,
                last_sale_date=str(sale_date) if sale_date is not None else None,
                price=_first(record, _PRICE_KEYS),
                coordinates=_extract_coords(record),
                raw=record,
            )
        )

    listings.sort(key=lambda listing: listing.last_sale_date or "", reverse=True)
    return listings[:limit]


class RealtyAPIClient(RealtyDataClient):
    """Recommended free provider: realtyapi.io, no credit card required.

    CAUTION on ``status``: a live call with ``status=sold`` came back with
    records whose own ``status`` field was ``"for_sale"`` — i.e. the API
    appears to ignore the value ``sold`` and return active listings. Since
    active listings mostly have old ``last_sold_date`` values, the recency
    filter will correctly reject them and the run can end with zero leads.
    The value is configurable (``REALTYAPI_STATUS``) so other candidates
    (e.g. ``recently_sold``) can be tried without code changes.
    """

    BASE_URL = "https://realtor.realtyapi.io/search/byzip"

    def __init__(self, api_key: str, timeout: float = 30.0, status: str = "sold"):
        self._api_key = api_key
        self._timeout = timeout
        self._status = status

    def fetch_recent_sales(self, location: str, limit: int, max_days_since_sale: int = 180) -> list[PropertyListing]:
        location = location.strip()
        if not _ZIP_RE.match(location):
            raise RealtyDataError(
                f"RealtyAPI provider only supports 5-digit ZIP codes as --location, got {location!r}"
            )
        data = request_json(
            "GET",
            self.BASE_URL,
            error_cls=RealtyDataError,
            error_context="RealtyAPI /search/byzip",
            timeout=self._timeout,
            headers={"x-realtyapi-key": self._api_key, "Accept": "application/json"},
            params={"zipCode": location, "status": self._status, "limit": min(limit * 3, 100)},
        )
        records = _extract_records(data)
        return _to_listings_realtyapi(records, limit, max_days_since_sale)


class RentCastClient(RealtyDataClient):
    """Recommended free provider: RentCast's native API."""

    BASE_URL = "https://api.rentcast.io/v1/properties"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def fetch_recent_sales(self, location: str, limit: int, max_days_since_sale: int = 180) -> list[PropertyListing]:
        params = {**_location_params(location), "limit": min(limit * 3, 100)}
        data = request_json(
            "GET",
            self.BASE_URL,
            error_cls=RealtyDataError,
            error_context="RentCast /properties",
            timeout=self._timeout,
            headers={"X-Api-Key": self._api_key, "Accept": "application/json"},
            params=params,
        )
        if not isinstance(data, list):
            raise RealtyDataError(f"RentCast /properties returned unexpected shape: {type(data).__name__}")
        return _to_listings(data, limit, max_days_since_sale)


class RealtyMoleRapidAPIClient(RealtyDataClient):
    """Legacy provider, as originally specified: Realty Mole via RapidAPI."""

    BASE_URL = "https://realty-mole-property-api.p.rapidapi.com/properties"
    HOST = "realty-mole-property-api.p.rapidapi.com"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def fetch_recent_sales(self, location: str, limit: int, max_days_since_sale: int = 180) -> list[PropertyListing]:
        params = {**_location_params(location), "limit": min(limit * 3, 100)}
        data = request_json(
            "GET",
            self.BASE_URL,
            error_cls=RealtyDataError,
            error_context="RapidAPI Realty Mole /properties",
            timeout=self._timeout,
            headers={"X-RapidAPI-Key": self._api_key, "X-RapidAPI-Host": self.HOST},
            params=params,
        )
        if not isinstance(data, list):
            raise RealtyDataError(
                f"RapidAPI Realty Mole /properties returned unexpected shape: {type(data).__name__}"
            )
        return _to_listings(data, limit, max_days_since_sale)


def build_realty_client(settings) -> RealtyDataClient:
    if settings.realty_provider == "realtyapi":
        return RealtyAPIClient(
            settings.realtyapi_key,
            timeout=settings.request_timeout,
            status=getattr(settings, "realtyapi_status", "sold"),
        )
    if settings.realty_provider == "rentcast":
        return RentCastClient(settings.rentcast_api_key, timeout=settings.request_timeout)
    if settings.realty_provider == "rapidapi_realtymole":
        return RealtyMoleRapidAPIClient(settings.rapidapi_key, timeout=settings.request_timeout)
    raise RealtyDataError(f"Unknown realty provider: {settings.realty_provider}")
