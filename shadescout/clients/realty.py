"""Step 1: Lead generation — find recently-sold homes in a target area.

RapidAPI's "Realty Mole Property API" was the free/cheap way to do this for
years, but Realty Mole was acquired and folded into RentCast. The RapidAPI
listing still works for existing subscribers, but for anyone starting fresh
the better free option today is RentCast's own API directly:
https://developers.rentcast.io — same underlying data, a genuinely free tier
(50 requests/month, no credit card), and it's actively maintained, whereas
the RapidAPI wrapper is legacy and can lag behind or disappear.

Both clients here return the exact same ``PropertyListing`` shape so the
rest of the pipeline doesn't care which provider produced it. The RapidAPI
client is kept for teams that already have a RapidAPI key/subscription.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from shadescout.errors import RealtyDataError
from shadescout.http import request_json
from shadescout.models import PropertyListing

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
    if settings.realty_provider == "rentcast":
        return RentCastClient(settings.rentcast_api_key, timeout=settings.request_timeout)
    if settings.realty_provider == "rapidapi_realtymole":
        return RealtyMoleRapidAPIClient(settings.rapidapi_key, timeout=settings.request_timeout)
    raise RealtyDataError(f"Unknown realty provider: {settings.realty_provider}")
