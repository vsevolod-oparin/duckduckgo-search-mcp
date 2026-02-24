"""
core/filters.py

URL and content filtering logic.

All filter lists are held in a FilterConfig dataclass so they can be read,
overridden, and persisted as MCP Resources without touching code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Tuple


# ---------------------------------------------------------------------------
# Default filter lists (match original web_research.py)
# ---------------------------------------------------------------------------

DEFAULT_BLOCKED_DOMAINS: Tuple[str, ...] = (
    "reddit.com", "twitter.com", "x.com", "facebook.com",
    "youtube.com", "tiktok.com", "instagram.com",
    "linkedin.com", "medium.com",
)

DEFAULT_SKIP_URL_PATTERNS: Tuple[str, ...] = (
    r"\.pdf$", r"\.jpg$", r"\.png$", r"\.gif$",
    r"/login", r"/signin", r"/signup", r"/cart", r"/checkout",
    r"amazon\.com/.*/(dp|gp)/", r"ebay\.com/itm/",
    r"/tag/", r"/tags/", r"/category/", r"/categories/",
    r"/topic/", r"/topics/", r"/archive/", r"/page/\d+",
    r"/shop/", r"/store/", r"/buy/", r"/product/", r"/products/",
)

DEFAULT_BLOCKED_CONTENT_MARKERS: Tuple[str, ...] = (
    "verify you are human",
    "access to this page has been denied",
    "please complete the security check",
    "cloudflare ray id:",
    "checking your browser",
    "enable javascript and cookies",
    "unusual traffic from your computer",
    "are you a robot",
    "captcha",
    "perimeterx",
    "distil networks",
    "blocked by",
)

DEFAULT_NAVIGATION_PATTERNS: Tuple[str, ...] = (
    "skip to",
    "jump to",
)


# ---------------------------------------------------------------------------
# FilterConfig — mutable, MCP-resource-backed
# ---------------------------------------------------------------------------

@dataclass
class FilterConfig:
    """
    Runtime-configurable filter lists.

    Instances are mutated when the MCP client writes the filter Resource,
    so all consumers must reference the same shared instance (see
    web_search_mcp/state.py).
    """
    blocked_domains: list[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_DOMAINS)
    )
    skip_url_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_SKIP_URL_PATTERNS)
    )
    blocked_content_markers: list[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_CONTENT_MARKERS)
    )
    navigation_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_NAVIGATION_PATTERNS)
    )

    # Compiled regex — rebuilt whenever lists change
    _compiled_url_pattern: re.Pattern | None = field(default=None, repr=False, compare=False)

    def rebuild_url_pattern(self) -> None:
        """(Re)compile the combined URL-block regex from current lists."""
        domain_part = "|".join(re.escape(d) for d in self.blocked_domains)
        pattern_part = "|".join(self.skip_url_patterns)
        combined = f"(?:{domain_part})|(?:{pattern_part})" if domain_part and pattern_part \
            else domain_part or pattern_part or "(?!)"
        self._compiled_url_pattern = re.compile(combined, re.IGNORECASE)

    def is_blocked_url(self, url: str) -> bool:
        if self._compiled_url_pattern is None:
            self.rebuild_url_pattern()
        return bool(self._compiled_url_pattern.search(url))  # type: ignore[union-attr]

    def is_blocked_content(self, content: str) -> bool:
        """Return True if content looks like a CAPTCHA or bot-block page."""
        if not content or len(content) < 30:
            return False
        content_lower = content[:2000].lower()
        return any(m in content_lower for m in self.blocked_content_markers)

    def is_navigation_line(self, line: str) -> bool:
        line_lower = line.lower()
        return any(line_lower.startswith(p) for p in self.navigation_patterns)


# ---------------------------------------------------------------------------
# Singleton shared instance — mutated by MCP Resource writes
# ---------------------------------------------------------------------------

_shared_filter_config: FilterConfig | None = None


def get_filter_config() -> FilterConfig:
    global _shared_filter_config
    if _shared_filter_config is None:
        _shared_filter_config = FilterConfig()
        _shared_filter_config.rebuild_url_pattern()
    return _shared_filter_config


def set_filter_config(cfg: FilterConfig) -> None:
    global _shared_filter_config
    cfg.rebuild_url_pattern()
    _shared_filter_config = cfg
