"""
core/pipeline.py

Async streaming research pipeline: search → parallel fetch → yield results.

The pipeline runs search and fetch concurrently via two asyncio tasks
communicating through queues (producer/consumer pattern).  Results are
yielded as an async generator so callers can either collect all results
(batch mode) or forward them incrementally (MCP streaming mode).
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncIterator, List, Optional

from .config import FetchResult, ResearchConfig, ResearchStats
from .ddg import DuckDuckGoSearch
from .fetcher import build_http_client, fetch_single_async, get_random_user_agent

logger = logging.getLogger(__name__)


async def run_pipeline(
    config: ResearchConfig,
) -> AsyncIterator[FetchResult]:
    """
    Async generator that yields FetchResult objects as they complete.

    Search and fetch run concurrently:
      - search_producer: runs DDG (sync) in a thread, pushes URLs into fetch_queue
      - fetch_consumer:  reads fetch_queue, fans out async fetches up to semaphore limit

    Sentinel value None terminates each queue.
    """
    stats = ResearchStats(query=config.query)
    fetch_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    result_queue: asyncio.Queue[Optional[FetchResult]] = asyncio.Queue()

    async def search_producer() -> None:
        loop = asyncio.get_event_loop()
        ddg = DuckDuckGoSearch()
        urls: List[str] = []

        def _search_sync() -> None:
            for url, _title in ddg.search(config.query, config.search_results):
                urls.append(url)
                stats.urls_searched = len(urls)
                loop.call_soon_threadsafe(fetch_queue.put_nowait, url)

        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(ex, _search_sync)

        await fetch_queue.put(None)  # signal end of search

    async def fetch_consumer(client: "httpx.AsyncClient") -> None:  # type: ignore[name-defined]
        semaphore = asyncio.Semaphore(config.max_concurrent)
        fetch_limit = config.fetch_count  # 0 = unlimited
        session_ua = get_random_user_agent()
        pending: List[asyncio.Task] = []

        async def fetch_one(url: str) -> None:
            async with semaphore:
                result = await fetch_single_async(
                    client, url,
                    config.timeout,
                    config.min_content_length,
                    config.max_content_length,
                    user_agent=session_ua,
                )
                await result_queue.put(result)

        while True:
            url = await fetch_queue.get()
            if url is None:
                break
            if fetch_limit == 0 or len(pending) < fetch_limit:
                pending.append(asyncio.create_task(fetch_one(url)))

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await result_queue.put(None)  # signal end of fetch

    async with build_http_client(config.max_concurrent, config.timeout) as client:
        asyncio.create_task(search_producer())
        asyncio.create_task(fetch_consumer(client))

        while True:
            result = await result_queue.get()
            if result is None:
                break
            if result.success:
                stats.urls_fetched += 1
                stats.content_chars += len(result.content)
            else:
                stats.urls_failed += 1
            yield result

    logger.info(
        "Pipeline done: %d/%d pages fetched (%d chars)",
        stats.urls_fetched, stats.urls_searched, stats.content_chars,
    )


async def collect_results(config: ResearchConfig) -> tuple[List[FetchResult], ResearchStats]:
    """
    Run the pipeline in batch mode, collecting all results.

    Returns (results_list, stats).
    """
    stats = ResearchStats(query=config.query)
    results: List[FetchResult] = []

    async for result in run_pipeline(config):
        results.append(result)
        if result.success:
            stats.urls_fetched += 1
            stats.content_chars += len(result.content)
        else:
            stats.urls_failed += 1

    stats.urls_searched = len(results)
    return results, stats
