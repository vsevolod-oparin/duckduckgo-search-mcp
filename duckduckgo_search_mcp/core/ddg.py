"""
core/ddg.py

DuckDuckGo search wrapper with early URL filtering and deduplication.
Runs synchronously (DDGS is sync) but is bridged to async via
ThreadPoolExecutor in the pipeline.
"""
from __future__ import annotations

import urllib.parse
import logging
from typing import Iterator, Set, Tuple

from ddgs import DDGS

from .filters import get_filter_config

logger = logging.getLogger(__name__)


def _is_valid_url(url: str) -> bool:
    try:
        r = urllib.parse.urlparse(url)
        return r.scheme in ("http", "https") and bool(r.netloc)
    except Exception:
        return False


class DuckDuckGoSearch:
    """
    Search DuckDuckGo and yield (url, title) tuples.

    Applies URL filtering and deduplication during iteration so that
    downstream code only receives clean, unique, fetchable URLs.
    """

    def search(
        self,
        query: str,
        num_results: int = 50,
    ) -> Iterator[Tuple[str, str]]:
        """
        Yield up to *num_results* (url, title) pairs from DuckDuckGo.

        Requests 2× from DDG to compensate for filtered/duplicate URLs.
        """
        filters = get_filter_config()
        seen_urls: Set[str] = set()
        count = 0

        try:
            ddg = DDGS(verify=False)
            for r in ddg.text(query, max_results=num_results * 2):
                url = r.get("href", "")
                if (
                    url
                    and url not in seen_urls
                    and _is_valid_url(url)
                    and not filters.is_blocked_url(url)
                ):
                    seen_urls.add(url)
                    yield url, r.get("title", "")
                    count += 1
                    if count >= num_results:
                        return
        except Exception as exc:
            logger.warning("DDG search error for %r: %s", query, exc)
