# SkyTrace — First to Finish

> **Project:** SkyTrace (package: `skytrace`)
> **Full path:** `C:\Users\LVST\Desktop\Vinesh\Satellite Position Tracker`
> **Last updated:** 2026-06-25
> **Tests:** 14/14 passing

---

## The Big Picture

A multi-agent satellite position tracker. You ask a question in plain English like *"Where is the ISS from Mumbai?"* and it returns live orbital data — distance, altitude, passes, satellites overhead — sourced from N2YO and Celestrak, with OpenStreetMap geocoding.

The architecture uses **Google ADK** (Agent Development Kit) to wire two agents together, an **MCP server** as the exclusive gateway to external APIs, and a **Rich-styled CLI** as the user interface (no TUI).

---

## What We Built

### Core Architecture

| Layer | What it does |
|-------|-------------|
| **CLI** (`__main__.py`) | Entry point. Renders a Unicode-block "SkyTrace" banner in a Rich double-line Panel. Connects to MCP server via `stdio_client`, wraps all 6 MCP tools, instantiates the Orchestrator. Has single-query and `--interactive` modes. |
| **UserNotificationAgent** (`agents/user_notification_agent.py`) | NLU layer. Parses intent (position/visual_passes/nearby/vague/help), extracts satellite name and location from natural language, geocodes places via TelemetryAgent, formats structured data into conversational answers. Handles vague queries ("what satellites are above...") separately via `_handle_vague_query`. |
| **TelemetryAgent** (`agents/telemetry_agent.py`) | Math and tool layer. Calls MCP tools exclusively — never makes direct HTTP requests. Computes true 3D slant range (ECEF), ground-track distance (Haversine), and elevation angle locally. Returns structured dicts only, no natural language. |
| **ADK Orchestrator** (`agents/orchestrator.py`) | `SatelliteTrackerOrchestrator` wires TelemetryAgent + UserNotificationAgent together using Google ADK `FunctionTool` wrappers. Exposes `run(user_query) -> str`. |
| **MCP Server** (`mcp_server/server.py`) | **The only module allowed to make HTTP calls** (enforced by `test_architecture.py`). Exposes 6 tools: `get_tle`, `get_satellite_position`, `get_visual_passes`, `geocode_place`, `reverse_geocode`, `get_satellites_above`. Uses `httpx` for async HTTP, `sgp4` for TLE propagation fallback. |
| **MCP Runner** (`mcp_server/main.py`) | Launches the MCP server on stdio transport. |

### Infra & Utilities

| Module | What it does |
|--------|-------------|
| **config.py** | Pydantic `Settings` from `.env` — N2YO key, Celestrak URL, rate limit config, timeouts, log level. Cached via `lru_cache`. |
| **models/** | Pydantic models: `SatellitePosition`, `TopocentricPosition`, `VisualPass`, `TLEData`, `OMMSatelliteData`, `GeocodeResult`, `UserRequest`, `AgentResponse`. Not all actively used in runtime — architecture scaffolding. |
| **rate_limiter.py** | Two implementations: `TokenBucket` (asyncio-safe, with acquire/try_acquire, refill) and `SlidingWindowRateLimiter` (precise window). `RateLimitExceeded` exception. Factory functions `create_n2yo_limiter()`, `create_sliding_n2yo_limiter()`. |
| **security.py** | `SecureCoordinates` — dataclass with `clear()`, context manager support, `__del__` cleanup. `CoordinateSanitizer` — regex-based lat/lon redaction for log messages, `sanitize_dict()` for structured data. |
| **geocoding.py** | Local in-memory cache for 15 world cities (Mumbai, London, Paris, Tokyo, NYC, etc.). Avoids Nominatim calls for common queries. |

### Testing (14 tests)

| Test file | Tests |
|-----------|-------|
| `test_architecture.py` (2) | Verifies no `httpx`/`requests` imports outside `mcp_server/`; verifies MCP server does import `httpx`. |
| `test_mcp_integration.py` (5) | Connects MCP client → server via `stdio_client`, tests `get_tle`, `geocode_place`, `get_visual_passes`, `reverse_geocode` (land + ocean fallback). |
| `test_rate_limiter.py` (7) | TokenBucket acquire/burst/timeout/refill; SlidingWindowRateLimiter max/enforce/remaining; N2YO bucket configuration. |

---

## Bug Fix History

| Bug | Fix |
|-----|-----|
| **Duplicate "currently over"** in ocean response | Removed "currently over" from `display_name` fallback in `_process_reverse_geocode_result` — ocean text was "currently over open ocean, currently over no nearby landmark" |
| **Nominatim Accept-Language missing** | Added `Accept-Language: en` header to both forward and reverse Nominatim calls |
| **`_satellites_above` Pydantic `__getattr__` crash** | Inlined the `get_satellites_above` call logic directly in `process()` method to bypass ADK's `__getattr__` intercept on private methods |
| **`get_satellites_above` tool not registered** | Added to `__main__.py` tools dict + MCP server `list_tools()` |
| **Test file encoding crash on Windows** | Switched `fpath.read_text()` to `fpath.read_text(encoding="utf-8")` in `test_architecture.py` — was crashing on cp1252 with Unicode banner chars |
| **CLI styling: missing banner chars** | Fixed truncated lines 3 and 4 of the Unicode block banner — trailing whitespace was missing, causing "c" and "e" chars to collapse |
| **Query text duplicated in output** | Removed `print(f"Query: {query}")` before separator in `__main__.py` |

---

## Features Added

| Feature | When |
|---------|------|
| Vague query detection (`classify_intent()` + `VAGUE_QUERY_TRIGGERS`) | Session 2026-06-25 |
| `_handle_vague_query()` + `format_satellites_above_response()` | Session 2026-06-25 |
| `get_satellites_above` MCP tool (N2YO `/above` endpoint) | Session 2026-06-25 |
| Rich Panel banner with fallback <50 cols | Session 2026-06-25 |
| Unicode `\u2500` separator instead of Rich markup | Session 2026-06-25 |
| `--interactive` mode | Session 2026-06-25 |
| Nominatim caching (in-memory, 5-min TTL, ~0.01° precision) | Earlier sessions |
| Local city cache (15 cities in `geocoding.py`) | Earlier sessions |
| Plain English docstrings across all 11 source files | Session 2026-06-25 |

---

## Files Removed

| File | Why |
|------|-----|
| `app.py` | Duplicate/abandoned TUI entry point |
| `tui.py` | TUI implementation (user chose not to keep it) |
| `skytrace.tcss` | Textual CSS stylesheet for the TUI |
| `src/satellite_tracker.egg-info/` | Stale egg-info from old package name |
| `src/skytrace.egg-info/` | Stale build artifact |

---

## Styling Decisions

All finalized in the last session (2026-06-25):

- **Banner:** Hardcoded Unicode block art "SKYTRACE" in a `Rich Panel` with `box=DOUBLE`, `border_style="white"`, no colors other than white border
- **Fallback:** Plain "SkyTrace" text when terminal <50 cols wide
- **Separators:** `\u2500` × 50 (flat Unicode box-drawing, not Rich markup)
- **Colors:** None in output text — white border on banner, flat text everywhere else
- **Console:** Single `Console()` instance reused
- **Alignment:** Panel centered with `expand=False`, padding `(1, 4)`

---

## Naming History

| Phase | Name |
|-------|------|
| Original project seed | `satellite-tracker` (package dir: `satellite_tracker/`) |
| Renamed (session 2026-06-25) | `skytrace` (package name), project name in pyproject.toml: "skytrace" |
| README / public-facing | "SkyTraceAI" at first, later simplified to "SkyTrace" |
| Current canonical | **SkyTrace** (display), `skytrace` (python package), `python -m skytrace` (CLI) |

---

## How To Use

```bash
# Single query
python -m skytrace "Where is the ISS from Mumbai?"

# Interactive mode
python -m skytrace --interactive

# Help
python -m skytrace --help

# Run tests
pytest -v
```

### Supported Query Types

| Example query | Intent | Route |
|---------------|--------|-------|
| "Where is the ISS from Mumbai?" | position | geocode → get_position → reverse_geocode → distance |
| "When will the ISS pass over Tokyo?" | visual_passes | geocode → get_visual_passes |
| "How far is Hubble from London?" | position | geocode → get_position → distance |
| "List satellites above New York City?" | vague | classify_intent → geocode → get_satellites_above |
| "What satellites are near Mumbai?" | nearby | geocode → get_satellites_above (90° radius, categorized) |
| "What can you do?" / "help" | help | Static help text |

---

## External Dependencies

| Dependency | Version | Used for |
|-----------|---------|----------|
| `google-adk` | ≥0.1.0 | Multi-agent orchestration (Agent, FunctionTool) |
| `mcp` | ≥1.0.0 | Model Context Protocol server + client SDK |
| `sgp4` | ≥2.22 | TLE orbit propagation (fallback when N2YO fails) |
| `skyfield` | ≥1.48 | Astronomy computations (declared, not actively used) |
| `python-dotenv` | ≥1.0.0 | .env file loading |
| `httpx` | ≥0.27.0 | Async HTTP client for N2YO, Celestrak, Nominatim |
| `pydantic` | ≥2.7.0 | Data models + settings |
| `pydantic-settings` | ≥2.3.0 | Pydantic BaseSettings from .env |
| `tenacity` | ≥8.2.0 | Retry logic (declared, used in earlier versions) |
| `textual` | ≥0.52.0 | Declared (TUI was removed) |
| `rich` | ≥13.7.0 | CLI banner and output rendering |

---

## Current State

- **All 14 tests pass** with no warnings
- **No TUI** — CLI-only; `app.py`, `tui.py`, `skytrace.tcss` deleted
- **No secrets in code** — all API keys from `.env`, verified
- **Docstrings simplified** — all 11 source files rewritten in plain English
- **Package installs** via `pip install -e "C:\Users\LVST\Desktop\Vinesh\Satellite Position Tracker"` (Windows absolute path required, not relative)
- **One initial commit** (the whole project seeded in one batch), then iterative improvements across multiple Hermes sessions
