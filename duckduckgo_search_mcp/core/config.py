"""
core/config.py

Shared dataclasses: ResearchConfig, FetchResult, ResearchStats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResearchConfig:
    """All tunable parameters for a research run (maps 1-to-1 to MCP tool input schema)."""
    query: str
    search_results: int = 50
    fetch_count: int = 0            # 0 = fetch all results
    max_content_length: int = 5000
    min_content_length: int = 600
    timeout: int = 20
    max_concurrent: int = 20
    output_format: str = "json"     # json | raw | markdown


@dataclass
class FetchResult:
    """Result for a single fetched URL."""
    url: str
    success: bool
    content: str = ""
    title: str = ""
    error: Optional[str] = None
    source: str = "direct"

    def to_dict(self) -> dict:
        d: dict = {"url": self.url, "success": self.success, "source": self.source}
        if self.success:
            d["title"] = self.title
            d["content"] = self.content
        else:
            d["error"] = self.error
        return d


@dataclass
class ResearchStats:
    """Counters accumulated during a research run."""
    query: str = ""
    urls_searched: int = 0
    urls_fetched: int = 0
    urls_failed: int = 0
    content_chars: int = 0

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "urls_searched": self.urls_searched,
            "urls_fetched": self.urls_fetched,
            "urls_failed": self.urls_failed,
            "content_chars": self.content_chars,
        }
