"""
web_search_mcp/server.py

MCP server entry point.

Exposes:
  Tools:
    • search_web   — DuckDuckGo search → list of {url, title}
    • fetch_page   — Fetch + extract a single URL
    • research     — Full search + parallel fetch pipeline (cached, streaming progress)

  Resources (readable + writable):
    • filters://blocked-domains      — list of blocked domain strings
    • filters://skip-url-patterns    — list of regex patterns for URL filtering
    • filters://blocked-content      — list of CAPTCHA/block detection markers
    • cache://stats                  — read-only cache statistics

  Prompts:
    • research_report  — Synthesis template for turning raw research into a report
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    Prompt,
    PromptMessage,
    ReadResourceResult,
    Resource,
    TextContent,
    Tool,
)

from .core.cache import get_cache
from .core.filters import FilterConfig, get_filter_config, set_filter_config
from .tools.fetch import handle_fetch_page
from .tools.research import handle_research
from .tools.search import handle_search_web

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    format="%(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template (loaded from prompts/ directory)
# ---------------------------------------------------------------------------

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
_RESEARCH_REPORT_TEMPLATE = """\
You are a research analyst synthesising web research results into a structured report.

## Instructions
- Write in clear, professional prose. Do NOT include raw URLs in the report body.
- Use the Source Name (page title) as attribution, e.g. "(Source Name)".
- Do NOT reproduce large verbatim passages — paraphrase and synthesise.
- Structure the report as shown below.

## Report Template

## Research: {topic}

**Stats**: {N} pages analysed

### Key Findings

1. **[Finding 1]**
   Supporting detail. (Source Name)

2. **[Finding 2]**
   Supporting detail. (Source Name)

### Data / Benchmarks

| Metric | Value | Source |
|--------|-------|--------|
| ...    | ...   | ...    |

### Summary

One or two paragraph synthesis of the most important takeaways.

### Sources

- Source Name 1
- Source Name 2
"""

try:
    _template_path = os.path.join(_PROMPTS_DIR, "research_report.md")
    with open(_template_path) as f:
        _RESEARCH_REPORT_TEMPLATE = f.read()
except FileNotFoundError:
    pass  # use inline default above


# ---------------------------------------------------------------------------
# Tool input schemas
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="search_web",
        description=(
            "Search DuckDuckGo and return a filtered list of URLs and titles. "
            "Blocked domains (reddit, twitter, facebook, youtube, tiktok, instagram, "
            "linkedin, medium) and low-value URL patterns (/tag/, /category/, /shop/, etc.) "
            "are filtered automatically. Use this when you only need links, or want to "
            "selectively fetch specific pages with fetch_page."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results to return (default 50, max 200)",
                    "default": 50,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="fetch_page",
        description=(
            "Fetch a single URL and extract its readable text content. "
            "Handles HTTP/2, CAPTCHA detection, 2 MB content cap, and HTML noise removal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Max characters of content to return (default 5000)",
                    "default": 5000,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds (default 20)",
                    "default": 20,
                },
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="research",
        description=(
            "Run a full web research pipeline: search DuckDuckGo, fetch all result pages "
            "in parallel (HTTP/2), return cleaned text content. Results are cached "
            "in-memory to avoid redundant searches. "
            "Use this for deep research tasks where you need content from many pages."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research query",
                },
                "search_results": {
                    "type": "integer",
                    "description": "Number of DDG results to request (default 50)",
                    "default": 50,
                },
                "fetch_count": {
                    "type": "integer",
                    "description": "Max pages to fetch (0 = fetch all results, default 0)",
                    "default": 0,
                },
                "max_content_length": {
                    "type": "integer",
                    "description": "Max characters per page (default 5000)",
                    "default": 5000,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Per-request timeout in seconds (default 20)",
                    "default": 20,
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": "Max parallel fetch connections (default 20)",
                    "default": 20,
                },
                "output_format": {
                    "type": "string",
                    "enum": ["json", "raw", "markdown"],
                    "description": "Response format: json (structured, best for LLMs), raw, or markdown (default json)",
                    "default": "json",
                },
                "use_cache": {
                    "type": "boolean",
                    "description": "Read from and write to cache (default true)",
                    "default": True,
                },
            },
            "required": ["query"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

RESOURCES = [
    Resource(
        uri="filters://blocked-domains",
        name="Blocked Domains",
        description="JSON array of domain strings that are excluded from search results and fetches.",
        mimeType="application/json",
    ),
    Resource(
        uri="filters://skip-url-patterns",
        name="Skip URL Patterns",
        description="JSON array of regex patterns. URLs matching any pattern are skipped.",
        mimeType="application/json",
    ),
    Resource(
        uri="filters://blocked-content",
        name="Blocked Content Markers",
        description="JSON array of strings. Pages containing any marker are treated as CAPTCHA/blocked.",
        mimeType="application/json",
    ),
    Resource(
        uri="cache://stats",
        name="Cache Statistics",
        description="Read-only cache statistics (memory entries).",
        mimeType="application/json",
    ),
]

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

app = Server("web-search-mcp")


@app.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    try:
        if name == "search_web":
            result = await handle_search_web(arguments)
        elif name == "fetch_page":
            result = await handle_fetch_page(arguments)
        elif name == "research":
            # Wire up progress notifications as MCP log messages
            async def _notify(msg: str) -> None:
                # MCP log notification — clients that support it will display this
                logger.info("PROGRESS: %s", msg)

            result = await handle_research(arguments, notify_progress=_notify)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        )
    except Exception as exc:
        logger.exception("Tool %r raised: %s", name, exc)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps({"error": str(exc)}))],
            isError=True,
        )


# ---------------------------------------------------------------------------
# Resources: list + read + write
# ---------------------------------------------------------------------------

@app.list_resources()
async def list_resources() -> ListResourcesResult:
    return ListResourcesResult(resources=RESOURCES)


@app.read_resource()
async def read_resource(uri: str) -> ReadResourceResult:
    filters = get_filter_config()
    cache   = get_cache()

    if uri == "filters://blocked-domains":
        data = json.dumps(filters.blocked_domains, indent=2)
    elif uri == "filters://skip-url-patterns":
        data = json.dumps(filters.skip_url_patterns, indent=2)
    elif uri == "filters://blocked-content":
        data = json.dumps(filters.blocked_content_markers, indent=2)
    elif uri == "cache://stats":
        data = json.dumps({
            "memory_entries": cache.memory_size,
        }, indent=2)
    else:
        data = json.dumps({"error": f"Unknown resource: {uri}"})

    return ReadResourceResult(
        contents=[TextContent(type="text", text=data)]
    )


# MCP does not yet have a universal write_resource decorator in all SDK versions,
# so we expose cache management and filter updates as tools too.

# We add three hidden management tools that power-users / orchestrators can call:
MANAGEMENT_TOOLS = [
    Tool(
        name="_update_filters",
        description=(
            "[Management] Update one or more filter lists at runtime. "
            "Changes take effect immediately for all subsequent requests. "
            "Pass only the fields you want to change."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "blocked_domains":       {"type": "array", "items": {"type": "string"}},
                "skip_url_patterns":     {"type": "array", "items": {"type": "string"}},
                "blocked_content_markers": {"type": "array", "items": {"type": "string"}},
                "navigation_patterns":   {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
    Tool(
        name="_cache_clear",
        description="[Management] Clear all cached research results (memory).",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="_cache_stats",
        description="[Management] Return current cache statistics.",
        inputSchema={"type": "object", "properties": {}},
    ),
]

TOOLS.extend(MANAGEMENT_TOOLS)


async def _handle_management(name: str, arguments: dict[str, Any]) -> dict:
    if name == "_update_filters":
        current = get_filter_config()
        new_cfg = FilterConfig(
            blocked_domains         = arguments.get("blocked_domains",         current.blocked_domains),
            skip_url_patterns       = arguments.get("skip_url_patterns",       current.skip_url_patterns),
            blocked_content_markers = arguments.get("blocked_content_markers", current.blocked_content_markers),
            navigation_patterns     = arguments.get("navigation_patterns",     current.navigation_patterns),
        )
        set_filter_config(new_cfg)
        return {"status": "ok", "message": "Filter config updated"}

    elif name == "_cache_clear":
        await get_cache().clear()
        return {"status": "ok", "message": "Cache cleared"}

    elif name == "_cache_stats":
        c = get_cache()
        return {"memory_entries": c.memory_size}

    return {"error": f"Unknown management tool: {name}"}


# Patch call_tool to also handle management tools
_original_call_tool = call_tool.__wrapped__ if hasattr(call_tool, "__wrapped__") else None


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:  # type: ignore[no-redef]
    try:
        if name == "search_web":
            result = await handle_search_web(arguments)
        elif name == "fetch_page":
            result = await handle_fetch_page(arguments)
        elif name == "research":
            async def _notify(msg: str) -> None:
                logger.info("PROGRESS: %s", msg)
            result = await handle_research(arguments, notify_progress=_notify)
        elif name.startswith("_"):
            result = await _handle_management(name, arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        )
    except Exception as exc:
        logger.exception("Tool %r raised: %s", name, exc)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps({"error": str(exc)}))],
            isError=True,
        )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@app.list_prompts()
async def list_prompts() -> ListPromptsResult:
    return ListPromptsResult(prompts=[
        Prompt(
            name="research_report",
            description=(
                "Template and instructions for synthesising raw web research results "
                "into a structured, well-cited markdown report."
            ),
        )
    ])


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    if name == "research_report":
        return GetPromptResult(
            description="Research report synthesis template",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(type="text", text=_RESEARCH_REPORT_TEMPLATE),
                )
            ],
        )
    raise ValueError(f"Unknown prompt: {name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _serve() -> None:
    logger.info("Starting web-search-mcp server")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
