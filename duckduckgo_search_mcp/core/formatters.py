"""
core/formatters.py

Output formatters: json (structured dict), raw (plain text), markdown.
"""
from __future__ import annotations

import json
from io import StringIO
from typing import List

from .config import FetchResult, ResearchStats


def format_json(results: List[FetchResult], stats: ResearchStats) -> dict:
    """Return structured dict suitable for direct MCP tool response."""
    successful = [r for r in results if r.success]
    return {
        "query": stats.query,
        "stats": stats.to_dict(),
        "content": [
            {"url": r.url, "title": r.title, "content": r.content, "source": r.source}
            for r in successful
        ],
    }


def format_raw(results: List[FetchResult]) -> str:
    buf = StringIO()
    for r in results:
        if r.success:
            buf.write(f"=== {r.url} ===\n")
            buf.write(r.content)
            buf.write("\n\n")
    return buf.getvalue()


def format_markdown(
    results: List[FetchResult],
    stats: ResearchStats,
    max_preview: int = 4000,
) -> str:
    successful = [r for r in results if r.success]
    buf = StringIO()
    buf.write(f"# Research: {stats.query}\n\n")
    buf.write(f"**Sources Analyzed**: {len(successful)} pages\n\n")
    buf.write("---\n\n")
    for r in successful:
        if r.content:
            title = r.title or r.url
            buf.write(f"## {title}\n")
            buf.write(f"*Source: {r.url}*\n\n")
            preview = r.content if len(r.content) <= max_preview else r.content[:max_preview] + "..."
            buf.write(preview)
            buf.write("\n\n---\n\n")
    return buf.getvalue()


def format_result_raw_single(result: FetchResult) -> str:
    """Single result for streaming raw output."""
    return f"=== {result.url} ===\n{result.content}\n"


def format_result_json_single(result: FetchResult) -> str:
    """Single result as JSON line (NDJSON) for streaming."""
    return json.dumps(result.to_dict(), ensure_ascii=False)
