#!/usr/bin/env python3
"""CLI entrypoint for the SkyTrace MCP server.

Usage:
    python -m skytrace.mcp_server.main
"""

import asyncio
import logging
import sys

# Configure basic logging before importing our modules so we can see startup logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from skytrace.mcp_server.server import run_mcp_server


def main() -> None:
    """Start the MCP server."""
    try:
        asyncio.run(run_mcp_server())
    except KeyboardInterrupt:
        logging.info("MCP server stopped by user")
        sys.exit(0)
    except Exception as exc:
        logging.exception("MCP server crashed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()