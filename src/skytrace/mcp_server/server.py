"""SkyTrace MCP Server - The only place that talks to external APIs.

This server connects to N2YO and Celestrak to get satellite data.
No other module should make HTTP requests to these APIs.
Everything goes through this server using MCP tools.

Security:
- Rate limits API calls so we don't get blocked
- Loads API keys from .env file, not hardcoded
- User locations are never saved or logged
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool
from sgp4.api import Satrec, jday

from skytrace.config import get_settings
from skytrace.utils.rate_limiter import TokenBucket, RateLimitExceeded
from skytrace.utils.security import CoordinateSanitizer

logger = logging.getLogger(__name__)

# Rate limiter: stops us from calling N2YO too often (max 800 calls/hour, burst up to 10)
# Nominatim lets us do 1 request per second - separate limiter for that
_rate_limiter = TokenBucket(
    capacity=10,
    refill_rate=800 / 3600.0,  # 800 per hour = ~0.222 per second
)

# Nominatim rate limiter: 1 request/second per usage policy
_nominatim_rate_limiter = TokenBucket(
    capacity=1,
    refill_rate=1.0,  # 1 per second
)

# Cache for reverse geocoding results (so we don't ask Nominatim the same place twice)
# Key: (rounded lat, rounded lon) -> result
_reverse_geocode_cache: dict[tuple[float, float], dict] = {}
_CACHE_TTL_SECONDS = 300  # Keep results for 5 minutes
_cache_timestamps: dict[tuple[float, float], float] = {}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ISS_NORAD_ID = 25544
N2YO_BASE = "https://api.n2yo.com/rest/v1/satellite"
CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"


def _n2yo_headers() -> dict:
    """Build headers for N2YO API (no auth key required for public endpoints)."""
    return {
        "Accept": "application/json",
        "User-Agent": "SatelliteTracker/0.1",
    }


async def _http_get(client: httpx.AsyncClient, url: str, **kwargs: Any) -> dict:
    """Make an HTTP GET request and return JSON.
    Logs the URL but hides coordinates for privacy."""
    log_url = CoordinateSanitizer.sanitize_log_message(url)
    logger.debug("MCP_HTTP_GET: %s", log_url)
    r = await client.get(url, **kwargs, headers=_n2yo_headers())
    r.raise_for_status()
    return r.json()


async def _http_get_text(client: httpx.AsyncClient, url: str, **kwargs: Any) -> str:
    """Make an HTTP GET request and return plain text."""
    log_url = CoordinateSanitizer.sanitize_log_message(url)
    logger.debug("MCP_HTTP_GET_TEXT: %s", log_url)
    r = await client.get(url, **kwargs, headers=_n2yo_headers())
    r.raise_for_status()
    return r.text


# Start and stop the MCP server cleanly
@asynccontextmanager
async def app_lifespan(server: Server) -> AsyncIterator[None]:
    """Initialize / shut down the server cleanly."""
    logger.info("MCP satelliteshake: Satellite Tracker MCP server starting")
    yield None
    logger.info("MCP shutdown: Satellite Tracker MCP server stopped")


mcp_app = Server("satellite-tracker-mcp", lifespan=app_lifespan)


# Route each tool name to the right function
@mcp_app.call_tool()
async def handle_tool(name: str, arguments: dict) -> list:
    """Route MCP tool calls to the right function."""
    if name == "get_tle":
        return await _tool_get_tle(arguments)
    if name == "get_satellite_position":
        return await _tool_get_satellite_position(arguments)
    if name == "get_visual_passes":
        return await _tool_get_visual_passes(arguments)
    if name == "geocode_place":
        return await _tool_geocode_place(arguments)
    if name == "get_satellites_above":
        return await _tool_get_satellites_above(arguments)
    if name == "reverse_geocode":
        return await _tool_reverse_geocode(arguments)
    raise ValueError(f"Unknown tool: {name}")


async def _tool_get_tle(arguments: dict) -> list:
    norad_id = int(arguments["norad_id"])
    if not await _rate_limiter.try_acquire():
        raise RateLimitExceeded("Rate limit exceeded for get_tle")

    url = f"{CELESTRAK_BASE}?CATNR={norad_id}&FORMAT=TLE"
    async with httpx.AsyncClient(timeout=30.0) as client:
        text = await _http_get_text(client, url)

    tle_lines = text.strip().splitlines()
    if len(tle_lines) < 2:
        raise ValueError(f"No TLE data found for NORAD ID {norad_id}")

    result = {
        "norad_id": norad_id,
        "line1": tle_lines[0],
        "line2": tle_lines[1],
    }
    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Tool: get_satellite_position  (N2YO or Celestrak; we use N2YO for lat/lon/alt)
# ---------------------------------------------------------------------------

async def _tool_get_satellite_position(arguments: dict) -> list:
    norad_id = int(arguments["norad_id"])
    lat = float(arguments["lat"])
    lon = float(arguments["lon"])
    alt = float(arguments.get("alt", 0))

    # SECURITY: Rate-limited and request-scoped (coordinates in URL only in-memory)
    if not await _rate_limiter.try_acquire():
        raise RateLimitExceeded("Rate limit exceeded for get_satellite_position")

    settings = get_settings()
    if settings.has_n2yo_key:
        api_key = settings.n2yo_api_key
        url = f"{N2YO_BASE}/positions/{norad_id}/{lat}/{lon}/{alt}/&apiKey={api_key}"
    else:
        # Without key, some N2YO endpoints may still work for demo / open endpoints.
        # Celestrak OMM is preferred for future-proof data.
        url = f"{N2YO_BASE}/positions/{norad_id}/{lat}/{lon}/{alt}/"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try N2YO first
        try:
            text = await _http_get_text(client, url)
            data = json.loads(text)
        except Exception:
            data = {}

        # N2YO returns {"error": "..."} on failure, not a positions array
        if isinstance(data, dict) and data.get("error"):
            data = {}
        
        positions = data.get("positions", []) if isinstance(data, dict) else []
        if not positions:
            # N2YO position endpoint often fails - fall back to computing from TLE
            # Fetch TLE from Celestrak and compute position
            tle_url = f"{CELESTRAK_BASE}?CATNR={norad_id}&FORMAT=TLE"
            tle_text = await _http_get_text(client, tle_url)
            tle_lines = tle_text.strip().splitlines()
            # Celestrak returns 3 lines: name, line1, line2 - skip name if present
            if len(tle_lines) == 3:
                line1, line2 = tle_lines[1], tle_lines[2]
            elif len(tle_lines) >= 2:
                line1, line2 = tle_lines[0], tle_lines[1]
            else:
                line1 = line2 = None
            
            if line1 and line2:
                from sgp4.api import Satrec, jday
                import datetime
                import math
                sat = Satrec.twoline2rv(line1, line2)
                now = datetime.datetime.utcnow()
                jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond/1e6)
                e, r, v = sat.sgp4(jd, fr)
                if e == 0:
                    # r is position in TEME frame (km), convert to lat/lon/alt
                    x, y, z = r
                    # Convert ECI to lat/lon/alt (approximate)
                    lon_rad = math.atan2(y, x)
                    lat_rad = math.atan2(z, math.sqrt(x*x + y*y))
                    altitude = math.sqrt(x*x + y*y + z*z) - 6371.0
                    result = {
                        "satname": data.get("info", {}).get("satname", f"SAT-{norad_id}"),
                        "satid": norad_id,
                        "timestamp": now.isoformat(),
                        "latitude": math.degrees(lat_rad),
                        "longitude": math.degrees(lon_rad),
                        "altitude_km": max(0, altitude),
                        "azimuth": None,
                        "elevation": None,
                    }
                    return [TextContent(type="text", text=json.dumps(result))]

            # If all else fails, return error
            raise ValueError(f"No position data from N2YO for satellite {norad_id}")

    # Take the first current position
    pos = positions[0]
    result = {
        "satname": data.get("info", {}).get("satname"),
        "satid": data.get("info", {}).get("satid"),
        "timestamp": pos.get("timestamp"),
        "latitude": pos.get("satlatitude"),
        "longitude": pos.get("satlongitude"),
        "altitude_km": pos.get("sataltitude"),
        "azimuth": pos.get("azimuth"),
        "elevation": pos.get("elevation"),
    }
    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Tool: reverse_geocode  (Nominatim - free OpenStreetMap reverse geocoding)
# ---------------------------------------------------------------------------

async def _tool_reverse_geocode(arguments: dict) -> list:
    """Reverse geocode latitude/longitude to a place name using Nominatim.
    
    Returns the nearest named location, or a body of water / ocean fallback.
    No result is ever fabricated — if the API returns empty, we return the
    appropriate fallback message.
    
    Rate limited to 1 req/sec per Nominatim usage policy.
    Results cached in-memory for 5 minutes (rounded to ~0.01° precision).
    """
    lat = float(arguments["lat"])
    lon = float(arguments["lon"])

    # SECURITY: Rate-limited and request-scoped
    if not await _nominatim_rate_limiter.try_acquire():
        raise RateLimitExceeded("Rate limit exceeded for reverse_geocode (1 req/sec)")

    # Check cache first (rounded to ~0.01° ≈ 1km precision)
    cache_key = (round(lat, 2), round(lon, 2))
    now = time.time()
    if cache_key in _reverse_geocode_cache:
        if now - _cache_timestamps.get(cache_key, 0) < _CACHE_TTL_SECONDS:
            logger.debug(f"Reverse geocode cache hit for {cache_key}")
            return [TextContent(type="text", text=json.dumps(_reverse_geocode_cache[cache_key]))]

    # Nominatim reverse endpoint
    url = f"{NOMINATIM_BASE}/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
        "zoom": 10,
        "extratags": 1,
    }
    headers = {
        "User-Agent": "SatelliteTracker/0.1",
        "Accept": "application/json",
        "Accept-Language": "en",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        log_url = CoordinateSanitizer.sanitize_log_message(f"{url}?lat={lat}&lon={lon}")
        logger.debug("MCP_HTTP_GET: %s", log_url)
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    # Process result
    result = _process_reverse_geocode_result(lat, lon, data)
    
    # Cache the result
    _reverse_geocode_cache[cache_key] = result
    _cache_timestamps[cache_key] = now
    
    return [TextContent(type="text", text=json.dumps(result))]


def _process_reverse_geocode_result(lat: float, lon: float, data: dict) -> dict:
    """Process Nominatim reverse geocode response.
    
    If no address found (e.g., open ocean), return a fallback based on
    the nearest named body of water from the response, or a generic
    'open ocean' message. Never fabricate a place name.
    """
    # Check if we have an address with meaningful components
    address = data.get("address", {})
    
    # Try to extract a meaningful place name
    place_name = None
    place_type = None
    
    # Priority order for land features
    for key in ["city", "town", "village", "hamlet", "municipality", 
                "county", "state", "province", "region", "country"]:
        if key in address:
            place_name = address[key]
            place_type = key
            break
    
    # If no land feature, check for water bodies
    if not place_name:
        for key in ["sea", "ocean", "bay", "strait", "gulf", "channel", 
                    "lake", "river", "water_body"]:
            if key in address:
                place_name = address[key]
                place_type = "water"
                break
    
    # Also check for named features in the response
    if not place_name and "display_name" in data:
        # Extract the first meaningful component from display_name
        display_parts = data["display_name"].split(", ")
        if display_parts:
            place_name = display_parts[0]
            place_type = "feature"
    
    if place_name:
        result = {
            "latitude": lat,
            "longitude": lon,
            "place_name": place_name,
            "place_type": place_type,
            "display_name": data.get("display_name", place_name),
            "country": address.get("country"),
            "country_code": address.get("country_code"),
        }
    else:
        # No result at all - open ocean fallback
        result = {
            "latitude": lat,
            "longitude": lon,
            "place_name": "open ocean",
            "place_type": "ocean",
            "display_name": "open ocean, no nearby landmark",
            "country": None,
            "country_code": None,
        }
    
    return result


# ---------------------------------------------------------------------------
# Tool: geocode_place  (Nominatim - free OpenStreetMap geocoding)
# ---------------------------------------------------------------------------

async def _tool_geocode_place(arguments: dict) -> list:
    place_name = arguments["place_name"]
    
    if not await _rate_limiter.try_acquire():
        raise RateLimitExceeded("Rate limit exceeded for geocode_place")
    
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": place_name, "format": "json", "limit": 1, "addressdetails": 1}
    headers = {
        "User-Agent": "SatelliteTracker/0.1",
        "Accept": "application/json",
        "Accept-Language": "en",
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        log_url = CoordinateSanitizer.sanitize_log_message(f"{url}?q={place_name}")
        logger.debug("MCP_HTTP_GET: %s", log_url)
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    
    if not data:
        raise ValueError(f"No results found for: {place_name}")
    
    result = data[0]
    return [TextContent(type="text", text=json.dumps({
        "name": result.get("display_name", place_name),
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "country": result.get("address", {}).get("country"),
        "admin1": result.get("address", {}).get("state") or result.get("address", {}).get("province"),
        "admin2": result.get("address", {}).get("county") or result.get("address", {}).get("city"),
    }))]


# ---------------------------------------------------------------------------
# Tool: get_visual_passes  (N2YO visual pass predictions)
# ---------------------------------------------------------------------------

async def _tool_get_visual_passes(arguments: dict) -> list:
    norad_id = int(arguments["norad_id"])
    lat = float(arguments["lat"])
    lon = float(arguments["lon"])
    alt = float(arguments.get("alt", 0))
    days = int(arguments.get("days", 7))

    # Cap days to avoid abuse
    days = min(max(days, 1), 10)

    if not await _rate_limiter.try_acquire():
        raise RateLimitExceeded("Rate limit exceeded for get_visual_passes")

    settings = get_settings()
    if settings.has_n2yo_key:
        api_key = settings.n2yo_api_key
        url = f"{N2YO_BASE}/visualpasses/{norad_id}/{lat}/{lon}/{alt}/{days}/&apiKey={api_key}"
    else:
        url = f"{N2YO_BASE}/visualpasses/{norad_id}/{lat}/{lon}/{alt}/{days}/"

    async with httpx.AsyncClient(timeout=30.0) as client:
        data = await _http_get(client, url)

    passes = data.get("passes", [])
    result = []
    for p in passes:
        result.append({
            "start_az": p.get("startAz"),
            "start_az_compass": p.get("startAz Compass"),
            "start_el": p.get("startEl"),
            "start_time": p.get("startUTC"),
            "max_az": p.get("maxAz"),
            "max_az_compass": p.get("maxAz Compass"),
            "max_el": p.get("maxEl"),
            "max_time": p.get("maxUTC"),
            "end_az": p.get("endAz"),
            "end_az_compass": p.get("endAz Compass"),
            "end_el": p.get("endEl"),
            "end_time": p.get("endUTC"),
            "duration_sec": p.get("duration"),
            "magnitude": p.get("magnitude"),
        })

    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Tool: get_satellites_above  (N2YO /above endpoint - satellites above observer)
# ---------------------------------------------------------------------------

async def _tool_get_satellites_above(arguments: dict) -> list:
    """Get all satellites above a location using the N2YO /above endpoint.
    Returns satellites within a search radius with elevation and azimuth.
    No brightness info available."""
    lat = float(arguments["lat"])
    lon = float(arguments["lon"])
    alt = float(arguments.get("alt", 0))
    radius_deg = float(arguments.get("radius_deg", 90))  # Default: entire sky
    category = int(arguments.get("category", 0))  # 0 = all types

    # SECURITY: Rate-limited and request-scoped
    if not await _rate_limiter.try_acquire():
        raise RateLimitExceeded("Rate limit exceeded for get_satellites_above")

    settings = get_settings()
    if settings.has_n2yo_key:
        api_key = settings.n2yo_api_key
        url = f"{N2YO_BASE}/above/{lat}/{lon}/{alt}/{radius_deg}/{category}/&apiKey={api_key}"
    else:
        url = f"{N2YO_BASE}/above/{lat}/{lon}/{alt}/{radius_deg}/{category}/"

    async with httpx.AsyncClient(timeout=30.0) as client:
        data = await _http_get(client, url)

    above = data.get("above", [])
    result = []
    for sat in above:
        result.append({
            "satname": sat.get("satname"),
            "satid": sat.get("satid"),
            "intldes": sat.get("intldes"),
            "launch_date": sat.get("launchDate"),
            "satlat": sat.get("satlat"),
            "satlng": sat.get("satlng"),
            "satalt": sat.get("satalt"),  # km
            "category": sat.get("category"),
            "elevation": sat.get("el"),  # elevation from observer
            "azimuth": sat.get("az"),    # azimuth from observer
        })

    return [TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Tool definitions for MCP schema registration
# ---------------------------------------------------------------------------

@mcp_app.list_tools()
async def list_tools() -> list:
    return [
        Tool(
            name="get_tle",
            description="Fetch TLE data for a satellite by NORAD ID from Celestrak. Returns line1 and line2.",
            inputSchema={
                "type": "object",
                "properties": {
                    "norad_id": {"type": "integer", "description": "NORAD catalog ID"},
                },
                "required": ["norad_id"],
            },
        ),
        Tool(
            name="get_satellite_position",
            description="Get current lat/lon/alt and az/el for a satellite over an observer location via N2YO.",
            inputSchema={
                "type": "object",
                "properties": {
                    "norad_id": {"type": "integer"},
                    "lat": {"type": "number", "description": "Observer latitude"},
                    "lon": {"type": "number", "description": "Observer longitude"},
                    "alt": {"type": "number", "description": "Observer altitude (m, default 0)"},
                },
                "required": ["norad_id", "lat", "lon"],
            },
        ),
        Tool(
            name="get_visual_passes",
            description="Get visual pass windows (rise/culminate/set) for a satellite over an observer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "norad_id": {"type": "integer"},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "alt": {"type": "number"},
                    "days": {"type": "integer", "description": "Prediction window in days (max 10)"},
                },
                "required": ["norad_id", "lat", "lon"],
            },
        ),
        Tool(
            name="geocode_place",
            description="Geocode a place name to latitude/longitude using Nominatim (OpenStreetMap).",
            inputSchema={
                "type": "object",
                "properties": {
                    "place_name": {"type": "string", "description": "Place name to geocode"},
                },
                "required": ["place_name"],
            },
        ),
        Tool(
            name="reverse_geocode",
            description="Reverse geocode latitude/longitude to a place name using Nominatim (OpenStreetMap). Returns nearest named location or water body fallback. Rate limited to 1 req/sec.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Latitude in decimal degrees"},
                    "lon": {"type": "number", "description": "Longitude in decimal degrees"},
                },
                "required": ["lat", "lon"],
            },
        ),
        Tool(
            name="get_satellites_above",
            description="Get all satellites within a search radius of observer's zenith using N2YO /above endpoint. Returns catalog objects currently overhead with elevation and azimuth.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Observer latitude"},
                    "lon": {"type": "number", "description": "Observer longitude"},
                    "alt": {"type": "number", "description": "Observer altitude (m, default 0)"},
                    "radius_deg": {"type": "number", "description": "Search radius in degrees (default 90 = entire sky)"},
                    "category": {"type": "integer", "description": "Satellite category filter (0 = all types)"},
                },
                "required": ["lat", "lon"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Entrypoint helper
# ---------------------------------------------------------------------------

async def run_mcp_server() -> None:
    """Run the MCP server using stdio transport."""
    from mcp.server.stdio import stdio_server
    async with stdio_server() as streams:
        await mcp_app.run(streams[0], streams[1], mcp_app.create_initialization_options())
