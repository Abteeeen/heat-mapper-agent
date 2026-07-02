"""Data structures passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lng: float

    def as_dict(self) -> dict:
        return {"lat": self.lat, "lng": self.lng}


@dataclass(frozen=True)
class PropertyListing:
    """A single recently-sold property returned by the realty data provider."""

    formatted_address: str
    last_sale_date: str | None = None
    price: float | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VisionAnalysis:
    has_patio: bool
    already_covered: bool
    estimated_sun_hours: int


@dataclass(frozen=True)
class QualifiedLead:
    property_address: str
    coordinates: Coordinates
    sun_hours: int
    postcard_text: str
    satellite_image_path: str | None = None
    street_view_image_path: str | None = None

    def to_dict(self) -> dict:
        result = {
            "lead_status": "QUALIFIED",
            "property_address": self.property_address,
            "coordinates": self.coordinates.as_dict(),
            "sun_hours": self.sun_hours,
            "postcard_text": self.postcard_text,
        }
        if self.satellite_image_path or self.street_view_image_path:
            result["images"] = {
                "satellite": self.satellite_image_path,
                "street_view": self.street_view_image_path,
            }
        return result
