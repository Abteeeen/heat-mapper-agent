"""Optional postcard personalization: an upcoming hot-day forecast.

Uses Open-Meteo (https://open-meteo.com), which is free and requires no API
key at all. This is best-effort only — if it fails for any reason, the
pipeline falls back to a postcard without a specific temperature/day.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import requests

from shadescout.models import Coordinates

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1/forecast"


def get_upcoming_hot_day(coords: Coordinates, timeout: float = 10.0) -> tuple[str, int] | None:
    """Return (weekday_name, forecast_high_f) for the hottest day in the next
    7 days, or None if the forecast can't be fetched.
    """
    try:
        response = requests.get(
            BASE_URL,
            timeout=timeout,
            params={
                "latitude": coords.lat,
                "longitude": coords.lng,
                "daily": "temperature_2m_max",
                "temperature_unit": "fahrenheit",
                "forecast_days": 7,
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        data = response.json()
        dates = data["daily"]["time"]
        highs = data["daily"]["temperature_2m_max"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.debug("Weather lookup failed, skipping postcard temperature: %s", exc)
        return None

    if not dates or not highs:
        return None

    hottest_index = max(range(len(highs)), key=lambda i: highs[i])
    hottest_date = datetime.fromisoformat(dates[hottest_index]).date()
    if hottest_date < date.today():
        return None
    return hottest_date.strftime("%A"), round(highs[hottest_index])
