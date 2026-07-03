"""Step 5 & 6: Vision analysis via OpenRouter, plus response parsing."""

from __future__ import annotations

import json
import re

from shadescout.errors import VisionAnalysisError
from shadescout.http import request_json
from shadescout.models import VisionAnalysis

# Required verbatim per the ShadeScout spec.
ANALYSIS_PROMPT = (
    "You are an expert landscape and shade analyst. Look at this satellite image of a residential property.\n"
    "1. Does this home have a backyard patio or deck? (Yes/No)\n"
    "2. Is there already a solid roof, pergola, or heavy tree cover shading the patio? (Yes/No)\n"
    "3. Based on the sun's trajectory (assume south-facing gets the most sun in the US), estimate how many "
    "hours of direct, punishing sunlight this patio gets per day.\n"
    "4. Return ONLY a valid JSON object exactly like this: "
    '{"has_patio": true, "already_covered": false, "estimated_sun_hours": 10}'
)

_IMAGE_CONTEXT_NOTE = (
    "Image 1 below is a top-down satellite view (zoom 20) of the property. "
    "Image 2 is a street-level view of the same address for additional context."
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict:
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise VisionAnalysisError(f"No JSON object found in vision model response: {text[:300]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise VisionAnalysisError(f"Vision model response was not valid JSON: {exc}") from exc


def _coerce_analysis(payload: dict) -> VisionAnalysis:
    try:
        has_patio = bool(payload["has_patio"])
        already_covered = bool(payload["already_covered"])
        estimated_sun_hours = int(payload["estimated_sun_hours"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VisionAnalysisError(f"Vision model JSON missing/invalid fields: {payload!r} ({exc})") from exc
    return VisionAnalysis(
        has_patio=has_patio,
        already_covered=already_covered,
        estimated_sun_hours=estimated_sun_hours,
    )


class VisionClient:
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "google/gemini-3.5-flash", timeout: float = 60.0):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def analyze_property(self, satellite_image_b64: str, street_view_image_b64: str) -> VisionAnalysis:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _IMAGE_CONTEXT_NOTE + "\n\n" + ANALYSIS_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{satellite_image_b64}"},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{street_view_image_b64}"},
                        },
                    ],
                }
            ],
        }
        data = request_json(
            "POST",
            self.BASE_URL,
            error_cls=VisionAnalysisError,
            error_context="OpenRouter vision analysis",
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionAnalysisError(f"Unexpected OpenRouter response shape: {data!r}") from exc

        payload_json = _extract_json_object(content)
        return _coerce_analysis(payload_json)
