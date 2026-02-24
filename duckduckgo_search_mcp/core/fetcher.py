"""
core/fetcher.py

Async HTTP/2 page fetcher with:
  - SSL verification disabled for reliability
  - CAPTCHA/block detection
  - Content-length guard (2 MB hard cap)
  - User-agent rotation (one UA per session)
  - Structured FetchResult output (never raises)
"""
from __future__ import annotations

import random
import ssl
import logging
from typing import Optional, Tuple

import httpx

from .config import FetchResult
from .extractor import extract_text, extract_title_from_content
from .filters import get_filter_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CONTENT_BYTES = 2_000_000  # 2 MB hard cap

USER_AGENTS: Tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
)

# ---------------------------------------------------------------------------
# SSL context singleton
# ---------------------------------------------------------------------------

_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def _get_ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context()
        _SSL_CONTEXT.check_hostname = False
        _SSL_CONTEXT.verify_mode = ssl.CERT_NONE
    return _SSL_CONTEXT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def _make_fetch_result(
    url: str,
    content: Optional[str],
    source: str,
    min_length: int,
    max_length: int,
) -> FetchResult:
    """Validate length, truncate, and build a successful FetchResult."""
    if content and len(content) >= min_length:
        if len(content) > max_length:
            content = content[:max_length] + "\n\n[Truncated...]"
        return FetchResult(
            url=url,
            success=True,
            content=content,
            title=extract_title_from_content(content),
            source=source,
        )
    return FetchResult(url=url, success=False, error="Content too short or empty")


# ---------------------------------------------------------------------------
# Core async fetch
# ---------------------------------------------------------------------------

async def fetch_single_async(
    client: httpx.AsyncClient,
    url: str,
    timeout: int,
    min_content_length: int,
    max_content_length: int,
    user_agent: str = "",
) -> FetchResult:
    """
    Fetch a single URL and return a FetchResult.

    Never raises — all errors are captured in FetchResult.error.
    """
    filters = get_filter_config()
    ua = user_agent or get_random_user_agent()

    try:
        resp = await client.get(
            url,
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            return FetchResult(url=url, success=False, error=f"HTTP {resp.status_code}")

        # Size guard (header-based, free check)
        cl = resp.headers.get("content-length")
        if cl and int(cl) > MAX_CONTENT_BYTES:
            return FetchResult(url=url, success=False, error="Content too large")

        raw = resp.text

        # CAPTCHA / bot-block detection
        if filters.is_blocked_content(raw):
            return FetchResult(url=url, success=False, error="CAPTCHA/blocked")

        content = extract_text(raw)
        return _make_fetch_result(url, content, "direct", min_content_length, max_content_length)

    except httpx.TimeoutException:
        return FetchResult(url=url, success=False, error="Timeout")
    except httpx.RequestError as exc:
        logger.debug("Request error for %s: %s", url, exc)
        return FetchResult(url=url, success=False, error="Request error")
    except Exception as exc:
        logger.debug("Unexpected error for %s: %s", url, exc)
        return FetchResult(url=url, success=False, error=f"Unexpected: {exc}")


# ---------------------------------------------------------------------------
# Shared async client factory
# ---------------------------------------------------------------------------

def build_http_client(max_concurrent: int, timeout: int) -> httpx.AsyncClient:
    """
    Build an httpx.AsyncClient tuned for parallel HTTP/2 fetching.

    Use as an async context manager:
        async with build_http_client(...) as client:
            ...
    """
    return httpx.AsyncClient(
        verify=False,
        http2=True,
        limits=httpx.Limits(
            max_connections=max_concurrent,
            max_keepalive_connections=max_concurrent,
            keepalive_expiry=30.0,
        ),
        timeout=httpx.Timeout(timeout, connect=5.0),
    )
