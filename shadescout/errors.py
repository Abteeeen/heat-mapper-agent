"""Exceptions raised across the ShadeScout pipeline.

Each stage raises a specific subclass so the pipeline can log a clear
reason and skip to the next property instead of crashing the whole run.
"""


class ShadeScoutError(Exception):
    """Base class for all recoverable ShadeScout errors."""


class ConfigError(ShadeScoutError):
    """Raised when required configuration/credentials are missing."""


class RealtyDataError(ShadeScoutError):
    """Raised when the property-listing provider fails or returns nothing usable."""


class GeocodingError(ShadeScoutError):
    """Raised when an address cannot be resolved to coordinates."""


class ImageryError(ShadeScoutError):
    """Raised when satellite or street view imagery cannot be retrieved."""


class VisionAnalysisError(ShadeScoutError):
    """Raised when the vision model call fails or returns unparseable output."""
