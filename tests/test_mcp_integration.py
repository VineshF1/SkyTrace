"""Integration test: connect MCP client to server and call tools."""

import asyncio
import pytest

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession


SERVER_PARAMS = StdioServerParameters(
    command="python",
    args=["-m", "skytrace.mcp_server.main"],
)


@pytest.mark.asyncio
async def test_mcp_server_get_tle():
    """Test get_tle tool via MCP client."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "get_tle" in tool_names
            
            # Call get_tle for ISS (NORAD 25544)
            result = await session.call_tool("get_tle", {"norad_id": 25544})
            assert result.content
            import json
            data = json.loads(result.content[0].text)
            assert data["norad_id"] == 25544
            assert "line1" in data
            assert "line2" in data


@pytest.mark.asyncio
async def test_mcp_server_geocode_place():
    """Test geocode_place tool via MCP client."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            result = await session.call_tool("geocode_place", {"place_name": "Paris"})
            assert result.content
            import json
            data = json.loads(result.content[0].text)
            # Nominatim may return slightly different coordinates for "Paris"
            assert 48.8 <= data["latitude"] <= 48.9
            assert 2.2 <= data["longitude"] <= 2.5
            assert "Paris" in data["name"]


@pytest.mark.asyncio
async def test_mcp_server_get_visual_passes():
    """Test get_visual_passes tool via MCP client."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            result = await session.call_tool("get_visual_passes", {
                "norad_id": 25544,
                "lat": 48.8566,
                "lon": 2.3522,
                "alt": 0,
                "days": 7
            })
            assert result.content
            import json
            data = json.loads(result.content[0].text)
            assert isinstance(data, list)


if __name__ == "__main__":
    asyncio.run(test_mcp_server_get_tle())
    print("get_tle test passed")
    asyncio.run(test_mcp_server_geocode_place())
    print("geocode_place test passed")
    asyncio.run(test_mcp_server_get_visual_passes())
    print("get_visual_passes test passed")
    asyncio.run(test_mcp_server_reverse_geocode_land())
    print("reverse_geocode_land test passed")
    asyncio.run(test_mcp_server_reverse_geocode_ocean())
    print("reverse_geocode_ocean test passed")
    print("All MCP integration tests passed!")


@pytest.mark.asyncio
async def test_mcp_server_reverse_geocode_land():
    """Test reverse_geocode tool via MCP client for a known land location (Paris)."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("reverse_geocode", {"lat": 48.8566, "lon": 2.3522})
            assert result.content
            import json
            data = json.loads(result.content[0].text)
            # Should return a place name, not open ocean
            assert data["place_name"] != "open ocean"
            assert data["place_type"] != "ocean"
            assert "Paris" in data["display_name"] or data["place_name"] == "Paris"
            assert data["country"] == "France"


@pytest.mark.asyncio
async def test_mcp_server_reverse_geocode_ocean():
    """Test reverse_geocode tool via MCP client for open ocean (should return fallback)."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("reverse_geocode", {"lat": 0.0, "lon": -120.0})
            assert result.content
            import json
            data = json.loads(result.content[0].text)
            # Should return open ocean fallback
            assert data["place_name"] == "open ocean"
            assert data["place_type"] == "ocean"
            assert "no nearby landmark" in data["display_name"].lower()
            assert data["country"] is None
            assert data["country_code"] is None