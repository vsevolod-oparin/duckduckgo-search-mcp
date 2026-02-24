"""
tools/fetch.py

MCP tool: fetch_page

Fetch a single URL and extract its readable text.
Handles CAPTCHA detection, 2 MB content cap, HTTP/2.
"""
from __future__ import annotations

from typing import Any

from ..core.fetcher import build_http_client, fetch_single_async, get_random_user_agent


async def handle_fetch_page(arguments: dict[str, Any]) -> dict:
    """
    Fetch one URL and return its extracted text content.

    Input schema:
        url         (str) required
        max_length  (int) optional — max chars (default 5000)
        timeout     (int) optional — seconds (default 20)

    Returns FetchResult as dict:
        {url, success, title?, content?, error?}
    """
    url = str(arguments.get("url", "")).strip()
    if not url:
        return {"error": "url is required"}

    max_length = int(arguments.get("max_length", 5000))
    timeout    = int(arguments.get("timeout", 20))

    ua = get_random_user_agent()

    async with build_http_client(max_concurrent=1, timeout=timeout) as client:
        result = await fetch_single_async(
            client, url,
            timeout=timeout,
            min_content_length=100,      # lenient for single-page fetch
            max_content_length=max_length,
            user_agent=ua,
        )

    return result.to_dict()
