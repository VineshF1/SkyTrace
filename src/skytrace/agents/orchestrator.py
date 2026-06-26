"""Sets up the Telemetry and Notification agents to work together.

The Orchestrator creates both agents and connects them.
The user talks to NotificationAgent, which asks TelemetryAgent for data.
TelemetryAgent gets data from the MCP server (which talks to N2YO/Celestrak).
"""

import asyncio
import logging
from typing import Any, Callable, Awaitable

from google.adk.tools import FunctionTool

from skytrace.agents.telemetry_agent import TelemetryAgent
from skytrace.agents.user_notification_agent import UserNotificationAgent

logger = logging.getLogger(__name__)


# Type for MCP tool functions
MCPToolFunc = Callable[..., Awaitable[dict]]


class SatelliteTrackerOrchestrator:
    """Orchestrates TelemetryAgent and UserNotificationAgent via ADK."""

    def __init__(self, mcp_tools: dict[str, MCPToolFunc]) -> None:
        self._telemetry_agent = TelemetryAgent(mcp_tools)
        self._user_agent = UserNotificationAgent(self._telemetry_agent)

    async def run(self, user_query: str) -> str:
        """Run the end-to-end satellite tracker pipeline."""
        return await self._user_agent.process(user_query)


def orchestrate(user_query: str, mcp_tools: dict[str, MCPToolFunc]) -> str:
    """Synchronous entry point."""
    return asyncio.run(SatelliteTrackerOrchestrator(mcp_tools).run(user_query))