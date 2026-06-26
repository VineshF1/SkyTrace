"""Security: keeps user locations private.

These utilities make sure coordinates are:
- Never saved to disk or logged
- Only kept in memory while a request runs
- Automatically cleared when done

Note: Python can't guarantee memory is wiped (that's up to garbage collection).
The real guarantee is: never logged, never saved, request-scoped only.
"""

import contextlib
import logging
import re
from typing import Any, Generator, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SecureCoordinates:
    """Holds user coordinates safely and cleans up when done.
    
    Safety rules:
    - Coordinates only live while a request is being handled
    - Never written to logs, disk, or databases
    - clear() removes the reference
    - Python's garbage collector decides when memory is actually freed
    """
    latitude: float
    longitude: float
    altitude_km: float = 0.0
    _cleared: bool = False
    
    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"Invalid latitude: {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"Invalid longitude: {self.longitude}")
        if self.altitude_km < 0:
            raise ValueError(f"Invalid altitude: {self.altitude_km}")
    
    def clear(self) -> None:
        self.latitude = 0.0
        self.longitude = 0.0
        self.altitude_km = 0.0
        self._cleared = True
    
    def __del__(self) -> None:
        if not self._cleared:
            self.clear()
    
    def __enter__(self) -> "SecureCoordinates":
        return self
    
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.clear()


@contextlib.contextmanager
def secure_coordinates(
    latitude: float,
    longitude: float,
    altitude_km: float = 0.0
) -> Generator[SecureCoordinates, None, None]:
    """Context manager for secure coordinate handling."""
    coords = SecureCoordinates(latitude, longitude, altitude_km)
    try:
        yield coords
    finally:
        coords.clear()
        logger.debug("Secure coordinates cleared after request")


class CoordinateSanitizer:
    """Utility to sanitize coordinates from logs and error messages."""
    
    COORD_PATTERNS = [
        r"lat(?:itude)?\s*[:=]\s*[-+]?\d*\.?\d+",
        r"lon(?:gitude)?\s*[:=]\s*[-+]?\d*\.?\d+",
        r"[-+]?\d{1,2}\.\d+,\s*[-+]?\d{1,3}\.\d+",
    ]
    
    @classmethod
    def sanitize_dict(cls, data: dict, keys_to_redact: Optional[list[str]] = None) -> dict:
        redact_keys = keys_to_redact or [
            "latitude", "longitude", "lat", "lon", "altitude",
            "observer_lat", "observer_lon", "observer_alt"
        ]
        result = {}
        for k, v in data.items():
            if k.lower() in [rk.lower() for rk in redact_keys]:
                result[k] = "[REDACTED]"
            elif isinstance(v, dict):
                result[k] = cls.sanitize_dict(v, keys_to_redact)
            elif isinstance(v, list):
                result[k] = [
                    cls.sanitize_dict(item, keys_to_redact) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result
    
    @classmethod
    def sanitize_log_message(cls, message: str) -> str:
        result = message
        for pattern in cls.COORD_PATTERNS:
            result = re.sub(pattern, "[COORDINATES REDACTED]", result, flags=re.IGNORECASE)
        return result


def sanitize_exception_for_logging(exc: Exception) -> str:
    return CoordinateSanitizer.sanitize_log_message(str(exc))