"""Tests verifying no direct HTTP calls outside the MCP server module."""

import os
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src" / "skytrace"
MCP_SERVER_DIR = SRC_DIR / "mcp_server"
HTTP_IMPORTS = ("import requests", "import httpx")


def test_no_direct_http_outside_mcp_server():
    """Assert that only the mcp_server module imports requests or httpx."""
    violations = []
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue

            fpath = Path(root) / fname
            relative = fpath.relative_to(SRC_DIR)

            # MCP server is the only allowed module for direct HTTP calls
            if str(relative).startswith("mcp_server"):
                continue

            content = fpath.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith(HTTP_IMPORTS):
                    violations.append(f"{relative}: {stripped}")

    assert not violations, f"Direct HTTP imports found outside mcp_server: {violations}"


def test_mcp_server_has_http_imports():
    """Assert the mcp_server module does contain HTTP client imports."""
    server_file = MCP_SERVER_DIR / "server.py"
    assert server_file.exists(), "MCP server module missing server.py"
    content = server_file.read_text(encoding="utf-8")
    assert "import httpx" in content, "MCP server should import httpx for direct HTTP calls"
