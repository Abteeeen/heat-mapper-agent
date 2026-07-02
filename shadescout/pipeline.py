"""Orchestrates Steps 2-7 of the ShadeScout workflow for a target location."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from shadescout.clients.geocoding import GeocodingClient
from shadescout.clients.imagery import ImageryClient
from shadescout.clients.realty import build_realty_client
from shadescout.clients.vision import VisionClient
from shadescout.clients.weather import get_upcoming_hot_day
from shadescout.config import Settings, load_settings
from shadescout.errors import ShadeScoutError
from shadescout.models import Coordinates, PropertyListing, QualifiedLead

logger = logging.getLogger(__name__)


def build_postcard_text(sun_hours: int, coords: Coordinates) -> str:
    hot_day = get_upcoming_hot_day(coords)
    if hot_day:
        day, temp_f = hot_day
        return (
            f"Your patio takes {sun_hours} hours of direct sun a day. "
            f"This {day} it hits {temp_f}°. Scan this QR code to see how a "
            "louvered pergola looks in your exact backyard."
        )
    return (
        f"Your patio takes {sun_hours} hours of direct, punishing sun a day. "
        "Scan this QR code to see how a louvered pergola looks in your exact backyard."
    )


def _save_image(image_dir: Path, address: str, suffix: str, image_b64: str) -> str:
    image_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() else "_" for c in address).strip("_")
    path = image_dir / f"{safe_name}_{suffix}.png"
    path.write_bytes(base64.b64decode(image_b64))
    return str(path)


def process_property(
    prop: PropertyListing,
    *,
    geocoder: GeocodingClient,
    imagery: ImageryClient,
    vision: VisionClient,
    save_images: bool,
    image_dir: Path | None,
) -> QualifiedLead | None:
    """Run Steps 3-7 for one property. Returns None if the lead is disqualified."""
    address = prop.formatted_address

    coords = geocoder.geocode(address)

    satellite_b64 = imagery.get_satellite_image_b64(coords)
    street_view_b64 = imagery.get_street_view_image_b64(coords)

    analysis = vision.analyze_property(satellite_b64, street_view_b64)

    if not analysis.has_patio or analysis.already_covered:
        logger.info(
            "Disqualified %s: has_patio=%s already_covered=%s",
            address,
            analysis.has_patio,
            analysis.already_covered,
        )
        return None

    satellite_path = street_view_path = None
    if save_images and image_dir is not None:
        satellite_path = _save_image(image_dir, address, "satellite", satellite_b64)
        street_view_path = _save_image(image_dir, address, "street", street_view_b64)

    postcard_text = build_postcard_text(analysis.estimated_sun_hours, coords)

    return QualifiedLead(
        property_address=address,
        coordinates=coords,
        sun_hours=analysis.estimated_sun_hours,
        postcard_text=postcard_text,
        satellite_image_path=satellite_path,
        street_view_image_path=street_view_path,
    )


def run(
    location: str,
    limit: int = 10,
    *,
    settings: Settings | None = None,
    save_images: bool = False,
    image_dir: str | Path = "images",
) -> list[QualifiedLead]:
    """Run the full ShadeScout pipeline for ``location`` and return qualified leads."""
    settings = settings or load_settings()

    realty_client = build_realty_client(settings)
    geocoder = GeocodingClient(settings.google_maps_api_key, timeout=settings.request_timeout)
    imagery = ImageryClient(settings.google_maps_api_key, timeout=settings.request_timeout)
    vision = VisionClient(
        settings.openrouter_api_key,
        model=settings.vision_model,
        timeout=max(settings.request_timeout, 60.0),
    )

    properties = realty_client.fetch_recent_sales(location, limit, settings.max_days_since_sale)
    logger.info("Found %d recently-sold properties in %s", len(properties), location)

    resolved_image_dir = Path(image_dir) if save_images else None
    leads: list[QualifiedLead] = []
    for prop in properties:
        try:
            lead = process_property(
                prop,
                geocoder=geocoder,
                imagery=imagery,
                vision=vision,
                save_images=save_images,
                image_dir=resolved_image_dir,
            )
        except ShadeScoutError as exc:
            logger.warning("Skipping %s: %s", prop.formatted_address, exc)
            continue

        if lead is not None:
            leads.append(lead)

    logger.info("Qualified %d/%d properties in %s", len(leads), len(properties), location)
    return leads
