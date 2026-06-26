"""Notification Agent: talks to the user in plain English.

This agent:
- Takes the user's question and figures out what they want
- Looks up place names through the Telemetry Agent
- Gets satellite data through the Telemetry Agent
- Turns the numbers into a friendly answer
- Never calls MCP or external APIs directly
"""

import logging
import re
from typing import Any

from google.adk import Agent

from skytrace.agents.telemetry_agent import TelemetryAgent

logger = logging.getLogger(__name__)


VAGUE_QUERY_TRIGGERS = [
    "what satellites",
    "any satellites",
    "satellites near",
    "satellites above",
    "satellites over",
    "satellites around",
    "what's above",
    "what is above",
    "anything above",
    "anything near",
    "anything overhead",
    "what's overhead",
    "what is overhead",
    "show me satellites",
    "list satellites",
    "satellites visible",
    "visible satellites",
]


class UserNotificationAgent(Agent):
    """User-facing agent that converts natural language to orbital answers.

    Responsibilities:
    1. Parse user request (e.g., "When will the ISS pass over Paris?")
    2. Resolve place names to lat/lon via Telemetry Agent (MCP geocode_place tool)
    3. Delegate data request to Telemetry Agent
    4. Translate structured output into friendly conversational response
    """

    def __init__(self, telemetry_agent: TelemetryAgent) -> None:
        super().__init__(name="UserNotificationAgent")
        self._telemetry = telemetry_agent
        # Default satellite mapping (name -> NORAD ID)
        self._satellites = {
            "iss": 25544,
            "hubble": 20580,
            "tiangong": 48274,
        }

    async def process(self, user_text: str) -> str:
        """Process a natural language user query.

        Args:
            user_text: User's natural language query.

        Returns:
            A conversational response string.
        """
        try:
            # Classify vague queries first (no specific satellite named)
            if self.classify_intent(user_text) == "vague":
                return await self._handle_vague_query(user_text)

            parsed = self._parse_request(user_text)

            if parsed["intent"] == "visual_passes":
                return await self._handle_visual_passes(parsed)
            elif parsed["intent"] == "position":
                return await self._handle_position(parsed)
            elif parsed["intent"] == "nearby":
                return await self._handle_nearby(parsed)
            elif parsed["intent"] == "help":
                return self._handle_help()
            else:
                return (
                    "I'm not sure how to answer that. "
                    "Try asking about when a satellite will pass over a city."
                )
        except Exception as exc:
            logger.exception("UserNotificationAgent error: %s", exc)
            return "Sorry, something went wrong processing your request. "

    def _parse_request(self, user_text: str) -> dict[str, Any]:
        """Parse the user query into structured intent.

        Simple keyword-based intent detection for demo purposes.
        """
        text_lower = user_text.lower()

        # Detect satellite
        satellite_name = None
        norad_id = None
        for name, sid in self._satellites.items():
            if name in text_lower:
                satellite_name = name
                norad_id = sid
                break

        # Default to ISS for demo
        if norad_id is None:
            satellite_name = "iss"
            norad_id = 25544

        # Detect intent
        if any(word in text_lower for word in ("pass", "passes", "when", "next", "visible", "see")):
            intent = "visual_passes"
        elif any(word in text_lower for word in ("where", "position", "locate", "above")):
            intent = "position"
        elif any(word in text_lower for word in ("near", "nearby", "overhead", "over me", "above me", "what satellites", "which satellites")):
            intent = "nearby"
        elif any(word in text_lower for word in ("help", "what can", "how do")):
            intent = "help"
        else:
            intent = "visual_passes"

        # Extract place name
        location_name = None
        for pattern in (
            r"from\s+([^?.,]+)",
            r"above\s+([^?.,]+)",
            r"over\s+([^?.,]+)",
            r"near\s+([^?.,]+)",
            r"in\s+([^?.,]+)",
            r"at\s+([^?.,]+)",
        ):
            m = re.search(pattern, text_lower)
            if m:
                location_name = m.group(1).strip().title()
                break

        # Try capitalized words as fallback
        if not location_name:
            words = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", user_text)
            if words:
                location_name = words[-1]

        # No default location - will ask or handle gracefully
        if not location_name:
            location_name = None

        return {
            "intent": intent,
            "satellite_name": satellite_name,
            "norad_id": norad_id,
            "location_name": location_name,
        }

    async def _handle_visual_passes(self, parsed: dict[str, Any]) -> str:
        """Handle visual pass query: geocode via telemetry, delegate, format."""
        # Step 1: Get location - if none provided, ask
        if not parsed["location_name"]:
            return "I need a location to check for satellite passes. Please specify a city or location (e.g., 'When will the ISS pass from Mumbai?')."

        # Step 1: Geocode via Telemetry Agent (which calls MCP geocode_place tool)
        geocode_response = await self._telemetry.process({
            "method": "geocode",
            "place_name": parsed["location_name"],
        })

        if not geocode_response["success"]:
            error = geocode_response.get("error", "Unknown error")
            return f"I couldn't find that location. {error}"

        geocode_result = geocode_response["data"]

        # Step 2: Delegate to Telemetry Agent for pass predictions
        telemetry_request = {
            "method": "passes",
            "norad_id": parsed["norad_id"],
            "lat": geocode_result["latitude"],
            "lon": geocode_result["longitude"],
            "alt": 0,
            "days": 7,
        }
        telemetry_response = await self._telemetry.process(telemetry_request)

        if not telemetry_response["success"]:
            error = telemetry_response.get("error", "Unknown error")
            return f"I couldn't get pass predictions right now. Error: {error}"

        # Step 3: Format as conversational response
        passes = telemetry_response["data"]
        if not passes:
            return (
                f"No visible passes of {parsed['satellite_name'].upper()} "
                f"are predicted from {geocode_result.get('name', parsed['location_name'])} "
                f"in the next 7 days."
            )

        lines = [
            f"Here are upcoming visible passes of {parsed['satellite_name'].upper()} "
            f"from {geocode_result.get('name', parsed['location_name'])}:",
            "",
        ]
        for i, p in enumerate(passes[:5], 1):
            start_time = p.get("start_time", "Unknown")
            start_az = p.get("start_az_compass", p.get("start_az", "N/A"))
            max_el = p.get("max_el", "N/A")
            duration = p.get("duration_sec", "N/A")
            lines.append(
                f"{i}. {start_time} UTC -- rises at {start_az}, peaks at {max_el} deg elevation, "
                f"duration {duration}s"
            )

        lines.append("")
        lines.append("Times are in UTC. Check local weather for best viewing conditions.")
        return "\n".join(lines)

    async def _handle_position(self, parsed: dict[str, Any]) -> str:
        # If no location provided, ask
        if not parsed["location_name"]:
            return "I need a location to check the satellite's position from. Please specify a city or location (e.g., 'Where is the ISS from Mumbai?')."

        # Geocode the location from the query (same as visual passes)
        geocode_response = await self._telemetry.process({
            "method": "geocode",
            "place_name": parsed["location_name"],
        })

        if not geocode_response["success"]:
            error = geocode_response.get("error", "Unknown error")
            return f"I couldn't find that location. {error}"

        geocode_result = geocode_response["data"]

        # Get distance information
        distance_response = await self._telemetry.process({
            "method": "distance",
            "norad_id": parsed["norad_id"],
            "lat": geocode_result["latitude"],
            "lon": geocode_result["longitude"],
            "alt": 0,
        })

        # Get position with observer location
        telemetry_request = {
            "method": "position",
            "norad_id": parsed["norad_id"],
            "lat": geocode_result["latitude"],
            "lon": geocode_result["longitude"],
            "alt": 0,
        }
        telemetry_response = await self._telemetry.process(telemetry_request)

        if not telemetry_response["success"]:
            return f"I could not get the current position. {telemetry_response.get('error', '')}"

        data = telemetry_response["data"]
        
        # Reverse geocode satellite position for user-friendly output
        sat_lat = data.get("latitude")
        sat_lon = data.get("longitude")
        
        location_description = ""
        if sat_lat is not None and sat_lon is not None:
            reverse_response = await self._telemetry.process({
                "method": "reverse_geocode",
                "lat": sat_lat,
                "lon": sat_lon,
            })
            if reverse_response["success"]:
                reverse_data = reverse_response["data"]
                place_name = reverse_data.get("place_name", "unknown location")
                place_type = reverse_data.get("place_type", "feature")
                display_name = reverse_data.get("display_name", place_name)
                
                if place_type == "ocean":
                    location_description = f"over {display_name}"
                elif place_type == "water":
                    location_description = f"over {place_name} ({display_name})"
                else:
                    location_description = f"over {place_name}, {reverse_data.get('country', '')}"
                
                location_description += f" (lat: {sat_lat:.4f}, lon: {sat_lon:.4f})"
            else:
                location_description = f"at latitude {sat_lat:.4f}, longitude {sat_lon:.4f}"
        else:
            location_description = "at unknown position"

        lines = [
            f"{parsed['satellite_name'].upper()} is currently {location_description}",
            f"Altitude: {data.get('altitude_km', 'N/A')} km",
        ]
        
        # Add distance info if available
        if distance_response["success"]:
            dist_data = distance_response["data"]
            slant_range = dist_data.get("slant_range_km")
            ground_track = dist_data.get("ground_track_km")
            elevation = dist_data.get("elevation_deg")
            
            if slant_range is not None:
                lines.append(f"Distance from {geocode_result.get('name', parsed['location_name'])}: {slant_range} km (line-of-sight)")
                if ground_track is not None:
                    lines.append(f"Ground track distance: {ground_track} km")
                if elevation is not None:
                    if elevation >= 0:
                        lines.append(f"Elevation: {elevation} deg (above horizon)")
                    else:
                        lines.append(f"Elevation: {elevation} deg (BELOW HORIZON - not visible)")
        
        # Only show elevation/azimuth if they have valid values (not None)
        elevation = data.get('elevation')
        azimuth = data.get('azimuth')
        if elevation is not None:
            lines.append(f"Elevation from {geocode_result.get('name', parsed['location_name'])}: {elevation} deg")
        if azimuth is not None:
            lines.append(f"Azimuth from {geocode_result.get('name', parsed['location_name'])}: {azimuth} deg")
        
        return "\n".join(lines)

    def _handle_help(self) -> str:
        return (
            "I can help you track satellites! Try asking:\n"
            "- 'Where is the ISS from Mumbai?'\n"
            "- 'When will the ISS pass over Tokyo?'\n"
            "- 'How far is Hubble from London?'\n"
        )

    @staticmethod
    def classify_intent(query: str) -> str:
        """
        Returns 'vague' or 'named'.
        Vague = no specific satellite named, user asking generally.
        Named = specific satellite or NORAD ID present.
        """
        q = query.lower()
        if any(trigger in q for trigger in VAGUE_QUERY_TRIGGERS):
            return "vague"
        return "named"

    async def _handle_vague_query(self, user_text: str) -> str:
        """Handle vague queries like 'what satellites are near Mumbai'."""
        parsed = self._parse_request(user_text)
        location = parsed.get("location_name")
        if not location:
            return "I need a location to check for satellites. Please specify a city or location (e.g., 'What satellites are over Mumbai?')."

        # Geocode via Telemetry Agent
        geocode_response = await self._telemetry.process({
            "method": "geocode",
            "place_name": location,
        })
        if not geocode_response["success"]:
            error = geocode_response.get("error", "Unknown error")
            return f"I couldn't find that location. {error}"

        geocode_result = geocode_response["data"]

        # Call satellites_above via Telemetry Agent
        result = await self._telemetry.process({
            "method": "satellites_above",
            "lat": geocode_result["latitude"],
            "lon": geocode_result["longitude"],
            "alt": 0,
            "radius_deg": 70,
            "category": 0,
        })

        if not result["success"]:
            error = result.get("error", "Unknown error")
            return f"I couldn't get satellite data right now. Error: {error}"

        return self.format_satellites_above_response(result["data"], geocode_result.get("name", location))

    def format_satellites_above_response(self, satellites: list, location: str) -> str:
        """
        Converts raw satellites_above API result into plain English.
        Returns hedged language — never claims certainty on visibility.
        """
        if not satellites:
            return f"No satellites found currently above {location}."

        top = satellites[:5]  # show top 5 only
        lines = [f"Currently above {location}, {len(satellites)} satellites detected. Top results:"]
        for sat in top:
            name = sat.get("satname", "Unknown")
            alt_km = sat.get("satalt", "?")
            lines.append(f"  \u2022 {name} \u2014 altitude {alt_km} km")
        lines.append("Note: visibility depends on time of day and weather conditions.")
        return "\n".join(lines)

    async def _handle_nearby(self, parsed: dict[str, Any]) -> str:
        """Handle 'what satellites are near/overhead' queries using get_satellites_above tool."""
        # If no location provided, ask
        if not parsed["location_name"]:
            return "I need a location to check what satellites are nearby. Please specify a city or location (e.g., 'What satellites are over Mumbai?')."

        # Geocode the location
        geocode_response = await self._telemetry.process({
            "method": "geocode",
            "place_name": parsed["location_name"],
        })

        if not geocode_response["success"]:
            error = geocode_response.get("error", "Unknown error")
            return f"I couldn't find that location. {error}"

        geocode_result = geocode_response["data"]

        # Get satellites via telemetry agent (which calls MCP tool)
        nearby_response = await self._telemetry.process({
            "method": "satellites_above",
            "lat": geocode_result["latitude"],
            "lon": geocode_result["longitude"],
            "alt": 0,
            "radius_deg": 90,  # Full sky
            "category": 0,  # All types
        })

        if not nearby_response["success"]:
            error = nearby_response.get("error", "Unknown error")
            return f"I couldn't get satellite data right now. Error: {error}"

        satellites = nearby_response["data"]
        if not satellites:
            return f"No satellites currently above {geocode_result.get('name', parsed['location_name'])}."

        # Format response - rank by elevation (highest first)
        # Satellites already have elevation data from N2YO
        satellites_above = [s for s in satellites if s.get("elevation", -90) > 0]
        satellites_above.sort(key=lambda s: s.get("elevation", -90), reverse=True)

        if not satellites_above:
            return f"No satellites currently above the horizon from {geocode_result.get('name', parsed['location_name'])}."

        lines = [
            f"Satellites currently above {geocode_result.get('name', parsed['location_name'])}:",
            "",
        ]
        
        # Prioritize: space stations (category 1) first, then others
        space_stations = [s for s in satellites_above if s.get("category") == 1]
        others = [s for s in satellites_above if s.get("category") != 1]
        
        for group, label in [(space_stations, "Space Stations"), (others, "Other Satellites")]:
            if group:
                lines.append(f"  {label}:")
                for i, s in enumerate(group[:5], 1):
                    name = s.get("satname", "Unknown")
                    elev = s.get("elevation", "N/A")
                    az = s.get("azimuth", "N/A")
                    alt = s.get("satalt", "N/A")
                    lines.append(f"    {i}. {name} - Elevation: {elev}°, Azimuth: {az}°, Alt: {alt} km")
                lines.append("")

        lines.append("Elevation > 0° means above horizon. Check for visibility conditions.")
        return "\n".join(lines)