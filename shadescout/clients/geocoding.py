"""Step 3: Geocoding — resolve a property address to lat/lng via Google."""

from __future__ import annotations

from shadescout.errors import GeocodingError
from shadescout.http import request_json
from shadescout.models import Coordinates


class GeocodingClient:
    BASE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def geocode(self, address: str) -> Coordinates:
        data = request_json(
            "GET",
            self.BASE_URL,
            error_cls=GeocodingError,
            error_context=f"Geocoding '{address}'",
            timeout=self._timeout,
            params={"address": address, "key": self._api_key},
        )
        status = data.get("status")
        if status != "OK":
            raise GeocodingError(
                f"Geocoding '{address}' failed: status={status}, "
                f"message={data.get('error_message', 'n/a')}"
            )
        results = data.get("results") or []
        if not results:
            raise GeocodingError(f"Geocoding '{address}' returned no results")
        location = results[0]["geometry"]["location"]
        return Coordinates(lat=location["lat"], lng=location["lng"])
