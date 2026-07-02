"""Step 4: Image acquisition — top-down satellite view + street-level context."""

from __future__ import annotations

import base64

from shadescout.errors import ImageryError
from shadescout.http import request_bytes
from shadescout.models import Coordinates


class ImageryClient:
    STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
    STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    def get_satellite_image(self, coords: Coordinates, *, zoom: int = 20, size: str = "640x640") -> bytes:
        return request_bytes(
            "GET",
            self.STATIC_MAP_URL,
            error_cls=ImageryError,
            error_context="Google Static Maps (satellite)",
            timeout=self._timeout,
            params={
                "center": f"{coords.lat},{coords.lng}",
                "zoom": zoom,
                "maptype": "satellite",
                "size": size,
                "key": self._api_key,
            },
        )

    def get_street_view_image(self, coords: Coordinates, *, size: str = "640x640") -> bytes:
        return request_bytes(
            "GET",
            self.STREET_VIEW_URL,
            error_cls=ImageryError,
            error_context="Google Street View Static API",
            timeout=self._timeout,
            params={
                "location": f"{coords.lat},{coords.lng}",
                "size": size,
                "key": self._api_key,
            },
        )

    def get_satellite_image_b64(self, coords: Coordinates, **kwargs) -> str:
        return base64.b64encode(self.get_satellite_image(coords, **kwargs)).decode("ascii")

    def get_street_view_image_b64(self, coords: Coordinates, **kwargs) -> str:
        return base64.b64encode(self.get_street_view_image(coords, **kwargs)).decode("ascii")
