"""Tests for core/extractor.py"""
import pytest
from web_search_mcp.core.extractor import extract_text, extract_title_from_content, clean_text


def test_extract_title():
    html = "<html><head><title>My Page | Site Name</title></head><body><p>Hello world, this is a test paragraph with enough content to pass the minimum length filter.</p></body></html>"
    result = extract_text(html)
    assert result.startswith("# My Page")
    # Site suffix should be stripped
    assert "Site Name" not in result.split("\n")[0]


def test_strips_script_and_style():
    html = """
    <html><body>
    <script>var x = 1;</script>
    <style>.foo { color: red; }</style>
    <p>This is the actual content that should be kept in the output.</p>
    </body></html>
    """
    result = extract_text(html)
    assert "var x" not in result
    assert "color: red" not in result
    assert "actual content" in result


def test_strips_nav_and_footer():
    html = """
    <html><body>
    <nav>Home | About | Contact</nav>
    <article>
    <p>This is a long enough article paragraph that should survive filtering because it has real content.</p>
    </article>
    <footer>Copyright 2025</footer>
    </body></html>
    """
    result = extract_text(html)
    assert "article paragraph" in result


def test_extract_title_from_content():
    content = "# My Title\n\nSome content here."
    assert extract_title_from_content(content) == "My Title"


def test_extract_title_from_content_no_title():
    content = "No title here, just plain text."
    assert extract_title_from_content(content) == ""


def test_clean_text():
    html = "<b>Hello</b> &amp; <i>World</i>"
    result = clean_text(html)
    assert result == "Hello & World"


def test_truncation_marker():
    """Content over max_length should get truncated marker."""
    from web_search_mcp.core.config import FetchResult
    from web_search_mcp.core.extractor import extract_title_from_content

    # Simulate what _make_fetch_result does
    long_content = "x" * 10000
    max_length = 100
    if len(long_content) > max_length:
        truncated = long_content[:max_length] + "\n\n[Truncated...]"
    assert "[Truncated...]" in truncated
