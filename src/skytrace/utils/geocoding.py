"""A local cache for common city coordinates.

Saves us from calling the geocoding API for well-known places.
For anything not in this list, the MCP server will ask Nominatim.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GeocodeError(Exception):
    pass


# Local cache for common locations (no external API call needed)
_COMMON_LOCATIONS = {
    "paris": (48.8566, 2.3522, "Paris, France"),
    "london": (51.5074, -0.1278, "London, UK"),
    "new york": (40.7128, -74.0060, "New York, USA"),
    "tokyo": (35.6762, 139.6503, "Tokyo, Japan"),
    "sydney": (-33.8688, 151.2093, "Sydney, Australia"),
    "los angeles": (34.0522, -118.2437, "Los Angeles, USA"),
    "moscow": (55.7558, 37.6173, "Moscow, Russia"),
    "beijing": (39.9042, 116.4074, "Beijing, China"),
    "dubai": (25.2048, 55.2708, "Dubai, UAE"),
    "singapore": (1.3521, 103.8198, "Singapore"),
    "hong kong": (22.3193, 114.1694, "Hong Kong"),
    "mumbai": (19.0760, 72.8777, "Mumbai, India"),
    "sao paulo": (-23.5505, -46.6333, "São Paulo, Brazil"),
    "cairo": (30.0444, 31.2357, "Cairo, Egypt"),
    "mexico city": (19.4326, -99.1332, "Mexico City, Mexico"),
}


def geocode_from_cache(place_name: str) -> Optional[dict]:
    """Look up a place name in the local cache.
    
    Returns dict with name, latitude, longitude or None if not found.
    """
    normalized = place_name.lower().strip()
    if normalized in _COMMON_LOCATIONS:
        lat, lon, name = _COMMON_LOCATIONS[normalized]
        logger.debug(f"Using cached coordinates for {place_name}")
        return {"name": name, "latitude": lat, "longitude": lon}
    return None


def list_common_locations() -> list[str]:
    """Return list of cached location names."""
    return list(_COMMON_LOCATIONS.keys())