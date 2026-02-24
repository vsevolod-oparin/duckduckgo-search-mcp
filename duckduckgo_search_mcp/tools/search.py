"""
tools/search.py

MCP tool: search_web

Lightweight DDG search returning a list of {url, title} objects.
No page fetching.  Useful when the client only needs links or wants to
selectively call fetch_page on specific results.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..core.ddg import DuckDuckGoSearch


async def handle_search_web(arguments: dict[str, Any]) -> dict:
    """
    Execute a DuckDuckGo search and return filtered URLs.

    Input schema:
        query        (str)  required — search query
        num_results  (int)  optional — max results (default 50)

    Returns:
        {
          "query": str,
          "count": int,
          "results": [ {"url": str, "title": str}, ... ]
        }
    """
    query = str(arguments.get("query", "")).strip()
    if not query:
        return {"error": "query is required"}

    num_results = int(arguments.get("num_results", 50))
    num_results = max(1, min(num_results, 200))

    ddg = DuckDuckGoSearch()
    results = []

    loop = asyncio.get_event_loop()

    def _run_search() -> list:
        return list(ddg.search(query, num_results))

    with ThreadPoolExecutor(max_workers=1) as ex:
        pairs = await loop.run_in_executor(ex, _run_search)

    results = [{"url": url, "title": title} for url, title in pairs]

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }
