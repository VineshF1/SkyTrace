"""Telemetry Agent: gets satellite data for other agents to use.

This agent asks the MCP server for satellite data. It never calls
external APIs directly. All data goes through the MCP server.
Output is numbers only - no natural language here.
"""

import json
import logging
import math
from typing import Any, Callable, Awaitable, Dict

from google.adk import Agent
from google.adk.tools import BaseTool

logger = logging.getLogger(__name__)

# Type for MCP tool functions
MCPToolFunc = Callable[..., Awaitable[dict]]

# Earth radius in km (WGS84 mean)
EARTH_RADIUS_KM = 6371.0


def _geocentric_to_ecef(lat_deg: float, lon_deg: float, alt_km: float) -> tuple:
    """Convert latitude/longitude/altitude to 3D Earth-centered coordinates.
    
    Simplified conversion - good enough for basic distance math.
    """
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)
    
    r = EARTH_RADIUS_KM + alt_km
    x = r * math.cos(lat_rad) * math.cos(lon_rad)
    y = r * math.cos(lat_rad) * math.sin(lon_rad)
    z = r * math.sin(lat_rad)
    
    return (x, y, z)


def _compute_slant_range_and_ground_distance(
    sat_lat: float, sat_lon: float, sat_alt_km: float,
    obs_lat: float, obs_lon: float, obs_alt_km: float
) -> tuple:
    """Calculate the straight-line distance and ground distance between satellite and observer.
    
    Returns:
        (slant_range_km, ground_track_km, elevation_deg)
    """
    # Convert both to Earth-centered coordinates
    sat_ecef = _geocentric_to_ecef(sat_lat, sat_lon, sat_alt_km)
    obs_ecef = _geocentric_to_ecef(obs_lat, obs_lon, obs_alt_km)
    
    # True 3D slant range (straight-line distance through space)
    dx = sat_ecef[0] - obs_ecef[0]
    dy = sat_ecef[1] - obs_ecef[1]
    dz = sat_ecef[2] - obs_ecef[2]
    slant_range_km = math.sqrt(dx*dx + dy*dy + dz*dz)
    
    # Ground track distance (Haversine formula along Earth's surface)
    sat_sub_lat = sat_lat
    sat_sub_lon = sat_lon
    dlat = math.radians(sat_sub_lat - obs_lat)
    dlon = math.radians(sat_sub_lon - obs_lon)
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(obs_lat)) * math.cos(math.radians(sat_sub_lat)) * 
         math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    ground_track_km = EARTH_RADIUS_KM * c
    
    # Calculate how high the satellite appears above the horizon
    range_vec = (dx, dy, dz)
    range_mag = slant_range_km
    
    # Observer's local 'up' direction in 3D space
    up = (obs_ecef[0]/math.sqrt(obs_ecef[0]**2 + obs_ecef[1]**2 + obs_ecef[2]**2),
          obs_ecef[1]/math.sqrt(obs_ecef[0]**2 + obs_ecef[1]**2 + obs_ecef[2]**2),
          obs_ecef[2]/math.sqrt(obs_ecef[0]**2 + obs_ecef[1]**2 + obs_ecef[2]**2))
    
    # Cosine of elevation angle
    cos_el = (range_vec[0]*up[0] + range_vec[1]*up[1] + range_vec[2]*up[2]) / range_mag
    elevation_deg = math.degrees(math.acos(max(-1, min(1, cos_el)))) - 90
    
    return (slant_range_km, ground_track_km, elevation_deg)


class TelemetryAgent(Agent):
    """Gets satellite data through MCP tools only.
    
    Rules:
    - Calls only MCP tools - no direct HTTP
    - Returns structured data (dicts, lists), not sentences
    """

    def __init__(self, mcp_tools: Dict[str, MCPToolFunc]) -> None:
        """
        Args:
            mcp_tools: Dict of MCP tool functions from the server.
        """
        super().__init__(name="TelemetryAgent")
        self._tools = mcp_tools
        self._sat_cache: dict[int, dict[str, Any]] = {}

    async def process(self, request: dict) -> dict:
        """Handle a telemetry request and route it to the right method.
        
        Request format:
            {
                "method": "position|passes|tle|geocode|reverse_geocode|distance|satellites_above",
                "norad_id": int,
                "lat": float (optional for TLE),
                "lon": float (optional for TLE),
                "alt": float (optional, default 0),
                "days": int (for passes, default 7),
                "place_name": str (for geocode),
            }
        
        Returns:
            {"success": bool, "data": dict, "error": str|None}
        """
        method = request.get("method")
        norad_id = request.get("norad_id")

        try:
            if method == "tle":
                return await self._get_tle(norad_id)
            elif method == "position":
                return await self._get_position(request)
            elif method == "passes":
                return await self._get_passes(request)
            elif method == "geocode":
                return await self._geocode_place(request)
            elif method == "reverse_geocode":
                return await self._reverse_geocode(request)
            elif method == "distance":
                return await self._distance(request)
            elif method == "satellites_above":
                lat = request.get("lat")
                lon = request.get("lon")
                alt = request.get("alt", 0)
                radius_deg = request.get("radius_deg", 70)
                category = request.get("category", 0)
                tool = self._tools.get("get_satellites_above")
                if not tool:
                    return {"success": False, "data": None, "error": "get_satellites_above tool unavailable"}
                result = await tool(lat=lat, lon=lon, alt=alt, radius_deg=radius_deg, category=category)
                return {"success": True, "data": json.loads(result["content"][0]["text"]), "error": None}
            else:
                return {"success": False, "data": None, "error": f"Unknown telemetry method: {method}"}
        except Exception as exc:
            logger.exception("TelemetryAgent error: %s", exc)
            return {"success": False, "data": None, "error": str(exc)}

    async def _get_tle(self, norad_id: int) -> dict:
        """Get TLE orbital data from the MCP server."""
        tool = self._tools.get("get_tle")
        if not tool:
            return {"success": False, "data": None, "error": "get_tle tool unavailable"}
        
        result = await tool(norad_id=norad_id)
        return {"success": True, "data": json.loads(result["content"][0]["text"]), "error": None}

    async def _get_position(self, request: dict) -> dict:
        """Get a satellite's current position from the MCP server."""
        tool = self._tools.get("get_satellite_position")
        if not tool:
            return {"success": False, "data": None, "error": "get_satellite_position tool unavailable"}
        
        result = await tool(
            norad_id=request["norad_id"],
            lat=request["lat"],
            lon=request["lon"],
            alt=request.get("alt", 0),
        )
        return {"success": True, "data": json.loads(result["content"][0]["text"]), "error": None}

    async def _get_passes(self, request: dict) -> dict:
        """Get upcoming visible passes from the MCP server."""
        tool = self._tools.get("get_visual_passes")
        if not tool:
            return {"success": False, "data": None, "error": "get_visual_passes tool unavailable"}
        
        result = await tool(
            norad_id=request["norad_id"],
            lat=request["lat"],
            lon=request["lon"],
            alt=request.get("alt", 0),
            days=request.get("days", 7),
        )
        return {"success": True, "data": json.loads(result["content"][0]["text"]), "error": None}

    async def _geocode_place(self, request: dict) -> dict:
        """Look up a place name to get its coordinates from the MCP server."""
        tool = self._tools.get("geocode_place")
        if not tool:
            return {"success": False, "data": None, "error": "geocode_place tool unavailable"}
        
        result = await tool(place_name=request["place_name"])
        return {"success": True, "data": json.loads(result["content"][0]["text"]), "error": None}

    async def _reverse_geocode(self, request: dict) -> dict:
        """Look up coordinates to get a place name from the MCP server."""
        tool = self._tools.get("reverse_geocode")
        if not tool:
            return {"success": False, "data": None, "error": "reverse_geocode tool unavailable"}
        
        result = await tool(lat=request["lat"], lon=request["lon"])
        return {"success": True, "data": json.loads(result["content"][0]["text"]), "error": None}

    async def _distance(self, request: dict) -> dict:
        """Calculate how far a satellite is from an observer.
        
        This is pure math - no external API calls.
        It gets the satellite position first, then runs the geometry.
        
        Math lives here (not in MCP server) because:
        1. MCP tools are for external data only
        2. This just processes data already fetched
        3. Keeps the architecture clean: MCP = talking to APIs, Telemetry = crunching numbers
        """
        norad_id = request.get("norad_id")
        obs_lat = request.get("lat")
        obs_lon = request.get("lon")
        obs_alt = request.get("alt", 0)
        
        if not norad_id or obs_lat is None or obs_lon is None:
            return {"success": False, "data": None, "error": "norad_id, lat, and lon required"}
        
        # Get satellite's current position first
        pos_response = await self._get_position({
            "norad_id": norad_id,
            "lat": obs_lat,
            "lon": obs_lon,
            "alt": obs_alt,
        })
        
        if not pos_response["success"]:
            return pos_response
        
        pos_data = pos_response["data"]
        sat_lat = pos_data.get("latitude")
        sat_lon = pos_data.get("longitude")
        sat_alt = pos_data.get("altitude_km")
        
        if sat_lat is None or sat_lon is None or sat_alt is None:
            return {"success": False, "data": None, "error": "Could not get satellite position"}
        
        # Run the distance calculation
        slant_range_km, ground_track_km, elevation_deg = _compute_slant_range_and_ground_distance(
            sat_lat, sat_lon, sat_alt,
            obs_lat, obs_lon, obs_alt
        )
        
        return {
            "success": True,
            "data": {
                "norad_id": norad_id,
                "slant_range_km": round(slant_range_km, 1),
                "ground_track_km": round(ground_track_km, 1),
                "elevation_deg": round(elevation_deg, 1),
                "satellite_position": {
                    "latitude": sat_lat,
                    "longitude": sat_lon,
                    "altitude_km": sat_alt,
                },
                "observer_position": {
                    "latitude": obs_lat,
                    "longitude": obs_lon,
                    "altitude_km": obs_alt,
                },
            },
            "error": None
        }


class TelemetryTool(BaseTool):
    """Wraps TelemetryAgent so ADK agents can call it as a tool."""

    def __init__(self, telemetry_agent: TelemetryAgent) -> None:
        super().__init__(name="telemetry_tool")
        self._agent = telemetry_agent

    async def run_async(self, args: dict, tool_context: Any = None) -> dict:
        return await self._agent.process(args)
