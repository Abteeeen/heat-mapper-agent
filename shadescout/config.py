"""Environment-driven configuration for ShadeScout.

All secrets are read from environment variables (optionally loaded from a
local .env file) so no API key is ever hard-coded in source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from shadescout.errors import ConfigError

load_dotenv()

VALID_REALTY_PROVIDERS = ("realtyapi", "rentcast", "rapidapi_realtymole")


@dataclass(frozen=True)
class Settings:
    google_maps_api_key: str
    openrouter_api_key: str
    realty_provider: str
    realtyapi_key: str | None
    rentcast_api_key: str | None
    rapidapi_key: str | None
    vision_model: str
    max_days_since_sale: int
    request_timeout: float


def load_settings() -> Settings:
    realty_provider = os.getenv("REALTY_PROVIDER", "realtyapi").strip().lower()
    if realty_provider not in VALID_REALTY_PROVIDERS:
        raise ConfigError(
            f"REALTY_PROVIDER must be one of {VALID_REALTY_PROVIDERS}, got {realty_provider!r}"
        )

    realtyapi_key = os.getenv("REALTYAPI_KEY")
    rentcast_api_key = os.getenv("RENTCAST_API_KEY")
    rapidapi_key = os.getenv("RAPIDAPI_KEY")
    if realty_provider == "realtyapi" and not realtyapi_key:
        raise ConfigError(
            "REALTYAPI_KEY is required when REALTY_PROVIDER=realtyapi. "
            "Get a free key (250 requests/month, no card) at https://www.realtyapi.io/"
        )
    if realty_provider == "rentcast" and not rentcast_api_key:
        raise ConfigError(
            "RENTCAST_API_KEY is required when REALTY_PROVIDER=rentcast. "
            "Get a free key (50 requests/month) at https://app.rentcast.io/app/api"
        )
    if realty_provider == "rapidapi_realtymole" and not rapidapi_key:
        raise ConfigError(
            "RAPIDAPI_KEY is required when REALTY_PROVIDER=rapidapi_realtymole."
        )

    google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not google_maps_api_key:
        raise ConfigError("GOOGLE_MAPS_API_KEY is required (Geocoding, Static Maps, Street View).")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        raise ConfigError("OPENROUTER_API_KEY is required for vision analysis.")

    return Settings(
        google_maps_api_key=google_maps_api_key,
        openrouter_api_key=openrouter_api_key,
        realty_provider=realty_provider,
        realtyapi_key=realtyapi_key,
        rentcast_api_key=rentcast_api_key,
        rapidapi_key=rapidapi_key,
        vision_model=os.getenv("VISION_MODEL", "anthropic/claude-3.5-sonnet"),
        max_days_since_sale=int(os.getenv("MAX_DAYS_SINCE_SALE", "180")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
    )
