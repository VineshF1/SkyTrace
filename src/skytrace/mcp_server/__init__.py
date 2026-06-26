"""MCP (Model Context Protocol) Server for Satellite Tracker.

This is the ONLY component that makes direct HTTP calls to N2YO and Celestrak APIs.
All other modules (agents, etc.) must route through this server using MCP tools.
"""