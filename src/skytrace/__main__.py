"""Root entrypoint and CLI for SkyTrace."""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Load environment variables before any other imports
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich import box

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from skytrace.agents.orchestrator import SatelliteTrackerOrchestrator

# Single Console instance reused across the whole CLI
console = Console()


def _render_banner() -> None:
    """Render the SkyTrace banner at startup using Rich double-line Panel.

    On terminals narrower than 50 chars, show a plain text fallback.
    """
    if console.width < 50:
        console.print("SkyTrace")
        console.print()
        return

    banner_text = (
        " ███████╗██╗  ██╗██╗   ██╗████████╗██████╗  █████╗  ██████╗███████╗\n"
        " ██╔════╝██║ ██╔╝╚██╗ ██╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝\n"
        " ███████╗█████╔╝  ╚████╔╝    ██║   ██████╔╝███████║██║     █████╗  \n"
        " ╚════██║██╔═██╗   ╚██╔╝     ██║   ██╔══██╗██╔══██║██║     ██╔══╝  \n"
        " ███████║██║  ██╗   ██║      ██║   ██║  ██║██║  ██║╚██████╗███████╗\n"
        " ╚══════╝╚═╝  ╚═╝   ╚═╝      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝"
    )

    console.print(
        Panel(
            f"{banner_text}\n"
            "         Satellite Position Tracker \u2022 Powered by ADK + MCP",
            border_style="white",
            box=box.DOUBLE,
            padding=(1, 4),
            width=100,
            expand=False,
        )
    )


async def run_with_real_mcp(user_query: str) -> str:
    """Connect to MCP server and run the user query."""
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp import ClientSession
    from mcp.types import TextContent

    params = StdioServerParameters(
        command="python",
        args=["-m", "skytrace.mcp_server.main"]
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Wrap MCP tools in async callables for the orchestrator
            async def mcp_tool(name: str):
                async def tool_func(**kwargs):
                    result = await session.call_tool(name, kwargs)
                    if result.content:
                        content = result.content[0]
                        if isinstance(content, TextContent):
                            return {"content": [{"type": "text", "text": content.text}]}
                        return {"content": [{"type": "text", "text": str(content)}]}
                    return {"content": [{"type": "text", "text": "{}"}]}
                return tool_func

            tools = {
                "get_tle": await mcp_tool("get_tle"),
                "get_satellite_position": await mcp_tool("get_satellite_position"),
                "get_visual_passes": await mcp_tool("get_visual_passes"),
                "geocode_place": await mcp_tool("geocode_place"),
                "reverse_geocode": await mcp_tool("reverse_geocode"),
                "get_satellites_above": await mcp_tool("get_satellites_above"),
            }

            orchestrator = SatelliteTrackerOrchestrator(tools)
            return await orchestrator.run(user_query)


def main() -> None:
    """CLI entrypoint for SkyTrace."""
    import argparse

    parser = argparse.ArgumentParser(
        description="SkyTrace - Ask about satellite passes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m skytrace "Where is the ISS from Mumbai?"
  python -m skytrace "List satellites above New York City?"
  python -m skytrace --interactive
        """,
    )
    parser.add_argument(
        "query",
        nargs="*",
        default=[],
        help="Natural language query about satellite passes (e.g., 'Where is the ISS located from Mumbai?')",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode (multiple queries)",
    )

    args = parser.parse_args()

    # Join query parts if provided
    query = " ".join(args.query) if args.query else ""

    # Render the banner at startup
    _render_banner()

    sep = "\u2500" * 50

    if args.interactive or not query:
        if not args.interactive:
            console.print("No query provided. Entering interactive mode...")
            console.print()
        console.print("Interactive mode - type your questions (Ctrl+C to exit)")
        console.print("Examples:")
        console.print("  Where is the ISS from Mumbai?")
        console.print("  List satellites above New York City?")
        console.print("  How far is Hubble from London?")
        console.print()
        while True:
            try:
                query = input("Query> ").strip()
                if not query:
                    continue
                console.print(sep)
                result = asyncio.run(run_with_real_mcp(query))
                console.print(result)
                console.print()
            except KeyboardInterrupt:
                console.print("\nGoodbye!")
                break
            except Exception as e:
                console.print(f"Error: {e}")
                console.print()
    else:
        console.print(sep)
        console.print("Connecting to MCP server...")
        console.print()

        try:
            result = asyncio.run(run_with_real_mcp(query))
            console.print(result)
        except Exception as e:
            console.print(f"Error: {e}")
            console.print(
                "Make sure dependencies are installed and network is available."
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
