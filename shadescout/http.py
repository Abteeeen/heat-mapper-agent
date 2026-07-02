"""Shared HTTP helper: retries transient failures, raises a caller-chosen
ShadeScoutError subclass on final failure so pipeline stages stay simple.
"""

from __future__ import annotations

from typing import Any

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from shadescout.errors import ShadeScoutError

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class _RetryableHTTPError(Exception):
    def __init__(self, response: requests.Response):
        self.response = response
        super().__init__(f"HTTP {response.status_code} from {response.url}")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (requests.ConnectionError, requests.Timeout, _RetryableHTTPError))


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_retryable),
)
def _do_request(method: str, url: str, *, timeout: float, **kwargs: Any) -> requests.Response:
    response = requests.request(method, url, timeout=timeout, **kwargs)
    if response.status_code in _RETRYABLE_STATUS_CODES:
        raise _RetryableHTTPError(response)
    return response


def request_json(
    method: str,
    url: str,
    *,
    error_cls: type[ShadeScoutError],
    error_context: str,
    timeout: float = 30.0,
    **kwargs: Any,
) -> Any:
    """Perform an HTTP request and return the parsed JSON body.

    Any network failure, non-2xx status, or invalid JSON is converted into
    ``error_cls`` so callers can catch one exception type per stage.
    """
    try:
        response = _do_request(method, url, timeout=timeout, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise error_cls(f"{error_context}: network error: {exc}") from exc
    except _RetryableHTTPError as exc:
        raise error_cls(
            f"{error_context}: HTTP {exc.response.status_code} after retries: {exc.response.text[:300]}"
        ) from exc

    if not response.ok:
        raise error_cls(f"{error_context}: HTTP {response.status_code}: {response.text[:300]}")

    try:
        return response.json()
    except ValueError as exc:
        raise error_cls(f"{error_context}: response was not valid JSON") from exc


def request_bytes(
    method: str,
    url: str,
    *,
    error_cls: type[ShadeScoutError],
    error_context: str,
    timeout: float = 30.0,
    **kwargs: Any,
) -> bytes:
    """Like ``request_json`` but returns the raw response body (for images)."""
    try:
        response = _do_request(method, url, timeout=timeout, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise error_cls(f"{error_context}: network error: {exc}") from exc
    except _RetryableHTTPError as exc:
        raise error_cls(
            f"{error_context}: HTTP {exc.response.status_code} after retries: {exc.response.text[:300]}"
        ) from exc

    if not response.ok:
        raise error_cls(f"{error_context}: HTTP {response.status_code}: {response.text[:300]}")

    return response.content
