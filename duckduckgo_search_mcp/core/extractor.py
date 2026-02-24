"""
core/extractor.py

HTML → clean readable text extraction.
All regex patterns are compiled once at module import.
"""
from __future__ import annotations

import re
from html import unescape
from typing import List

from .filters import get_filter_config

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

RE_STRIP_TAGS   = re.compile(
    r"<(script|style|nav|footer|header|aside|noscript)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
RE_COMMENTS     = re.compile(r"<!--.*?-->", re.DOTALL)
RE_TITLE        = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
RE_BR           = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_BLOCK_END    = re.compile(r"</(p|div|h[1-6]|li|tr|article|section)>", re.IGNORECASE)
RE_LI           = re.compile(r"<li[^>]*>", re.IGNORECASE)
RE_ALL_TAGS     = re.compile(r"<[^>]+>")
RE_SPACES       = re.compile(r"[ \t]+")
RE_LEADING_SP   = re.compile(r"\n[ \t]+")
RE_MULTI_NL     = re.compile(r"\n{3,}")
RE_WHITESPACE   = re.compile(r"\s+")
RE_SITE_SUFFIX  = re.compile(r'\s*[\|\-–—]\s*[^|\-–—]{3,50}$')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    if not text:
        return ""
    text = unescape(text)
    text = RE_ALL_TAGS.sub("", text)
    text = RE_WHITESPACE.sub(" ", text)
    return text.strip()


def extract_title_from_content(content: str) -> str:
    """Extract the title line from markdown-formatted content (# Title)."""
    if content.startswith("# "):
        newline = content.find("\n")
        if newline > 0:
            return content[2:newline]
    return ""


def extract_text(html: str) -> str:
    """
    Extract readable text from an HTML page.

    Pipeline:
      1. Strip semantic noise tags (script, style, nav, footer …)
      2. Strip HTML comments
      3. Extract <title> and clean site-suffix
      4. Convert structural tags to newlines / bullets
      5. Strip remaining tags, unescape entities, normalise whitespace
      6. Line-level noise filter (navigation, symbol spam, UI fragments,
         short-line collapsing)
      7. Prepend "# {title}" if a title was found
    """
    filters = get_filter_config()

    # Stage 1-2: structural noise removal
    html = RE_STRIP_TAGS.sub("", html)
    html = RE_COMMENTS.sub("", html)

    # Stage 3: title extraction
    title_match = RE_TITLE.search(html)
    raw_title = unescape(title_match.group(1).strip()) if title_match else ""
    title = RE_SITE_SUFFIX.sub("", raw_title) if raw_title else ""

    # Stage 4: structural → whitespace conversion
    html = RE_BR.sub("\n", html)
    html = RE_BLOCK_END.sub("\n\n", html)
    html = RE_LI.sub("• ", html)

    # Stage 5: strip tags, normalise
    text = RE_ALL_TAGS.sub(" ", html)
    text = unescape(text)
    text = RE_SPACES.sub(" ", text)
    text = RE_LEADING_SP.sub("\n", text)
    text = RE_MULTI_NL.sub("\n\n", text)

    # Stage 6: line-level filter
    lines: List[str] = []
    short_buffer: List[str] = []
    prev_line = ""
    title_seen = False

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Navigation lines
        if filters.is_navigation_line(line):
            continue

        # Symbol-heavy lines (nav remnants)
        alnum_count = sum(1 for c in line if c.isalnum())
        if len(line) > 3 and alnum_count / len(line) < 0.3:
            continue

        # Excessive bullet characters
        bullet_count = sum(1 for c in line if c in "•·●○◦‣⁃")
        if bullet_count >= 4:
            continue

        # Pure list markers
        stripped = line.strip("•-*·►▸▹→‣⁃● ")
        if not stripped or len(stripped) < 2:
            continue

        # Duplicate of previous line
        if line == prev_line:
            continue

        # Duplicate title line
        if title and not title_seen:
            line_norm = RE_SITE_SUFFIX.sub("", line)
            if line_norm == title or line == raw_title:
                title_seen = True
                continue

        # Single/double-word UI fragments
        words = line.split()
        if len(line) < 15 and len(words) <= 2 and not line.startswith("#"):
            if not any(c.islower() for c in line):
                continue

        # Collapse runs of short lines
        if len(line) < 25 and not line.startswith("#"):
            short_buffer.append(line)
            if len(short_buffer) >= 5:
                joined = " | ".join(short_buffer)
                if len(joined) < 300:
                    lines.append(joined)
                short_buffer = []
        else:
            if short_buffer:
                if len(short_buffer) <= 2:
                    lines.extend(short_buffer)
                else:
                    lines.append(" | ".join(short_buffer))
                short_buffer = []
            lines.append(line)
            prev_line = line

    # Flush remaining short buffer
    if short_buffer:
        if len(short_buffer) <= 2:
            lines.extend(short_buffer)
        else:
            lines.append(" | ".join(short_buffer))

    text = RE_MULTI_NL.sub("\n\n", "\n".join(lines)).strip()

    if title:
        text = f"# {title}\n\n{text}"
    return text
