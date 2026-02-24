"""
tools/research.py

MCP tool: research

Full search + fetch pipeline with:
  - Parallel HTTP/2 fetching
  - In-memory caching (keyed on query + params)
  - MCP progress notifications during long runs
  - Structured JSON response by default; raw/markdown optional
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable, Optional

from ..core.cache import get_cache, make_cache_key
from ..core.config import ResearchConfig, ResearchStats
from ..core.formatters import format_json, format_raw, format_markdown
from ..core.pipeline import collect_results

logger = logging.getLogger(__name__)

# Type for the optional MCP progress notification callback
ProgressCallback = Optional[Callable[[str], Awaitable[None]]]


async def handle_research(
    arguments: dict[str, Any],
    notify_progress: ProgressCallback = None,
) -> dict:
    """
    Run a full web research pipeline and return results.

    Input schema:
        query               (str)  required
        search_results      (int)  optional — DDG results to request (default 50)
        fetch_count         (int)  optional — max pages to fetch; 0 = all (default 0)
        max_content_length  (int)  optional — chars per page (default 5000)
        timeout             (int)  optional — fetch timeout seconds (default 20)
        max_concurrent      (int)  optional — parallel connections (default 20)
        output_format       (str)  optional — json | raw | markdown (default json)
        use_cache           (bool) optional — read/write cache (default true)

    Returns (output_format=json):
        {
          "query": str,
          "cached": bool,
          "stats": { urls_searched, urls_fetched, urls_failed, content_chars },
          "content": [ {"url", "title", "content", "source"}, ... ]
        }
    """
    query = str(arguments.get("query", "")).strip()
    if not query:
        return {"error": "query is required"}

    config = ResearchConfig(
        query=query,
        search_results  = int(arguments.get("search_results",     50)),
        fetch_count     = int(arguments.get("fetch_count",          0)),
        max_content_length = int(arguments.get("max_content_length", 5000)),
        timeout         = int(arguments.get("timeout",              20)),
        max_concurrent  = int(arguments.get("max_concurrent",       20)),
        output_format   = str(arguments.get("output_format",     "json")),
    )
    use_cache = bool(arguments.get("use_cache", True))

    # Build cache key from all params that affect results
    cache_key = make_cache_key(
        query,
        search_results=config.search_results,
        fetch_count=config.fetch_count,
        max_content_length=config.max_content_length,
    )

    cache = get_cache()

    # --- Cache read ---
    if use_cache:
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.info("Returning cached result for %r", query)
            cached["cached"] = True
            return cached

    # --- Progress notification: starting ---
    if notify_progress:
        await notify_progress(f'Starting research: "{query}"')

    # --- Run pipeline ---
    results, stats = await collect_results(config)

    if notify_progress:
        await notify_progress(
            f"Fetched {stats.urls_fetched}/{stats.urls_searched} pages "
            f"({stats.content_chars:,} chars)"
        )

    # --- Format output ---
    output_format = config.output_format.lower()

    if output_format == "raw":
        response: dict = {
            "query": query,
            "cached": False,
            "stats": stats.to_dict(),
            "content": format_raw(results),
        }
    elif output_format == "markdown":
        response = {
            "query": query,
            "cached": False,
            "stats": stats.to_dict(),
            "content": format_markdown(results, stats, config.max_content_length),
        }
    else:
        # json (default) — structured, best for LLM consumption
        response = format_json(results, stats)
        response["cached"] = False

    # --- Cache write ---
    if use_cache and stats.urls_fetched > 0:
        await cache.set(cache_key, response)

    return response
