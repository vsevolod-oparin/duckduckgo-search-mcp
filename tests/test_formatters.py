"""Tests for core/formatters.py"""
import json
import pytest
from web_search_mcp.core.config import FetchResult, ResearchStats
from web_search_mcp.core.formatters import (
    format_json,
    format_markdown,
    format_raw,
    format_result_json_single,
    format_result_raw_single,
)


def _make_results():
    return [
        FetchResult(url="https://a.com", success=True, title="Page A", content="Content A"),
        FetchResult(url="https://b.com", success=False, error="Timeout"),
        FetchResult(url="https://c.com", success=True, title="Page C", content="Content C"),
    ]


def _make_stats():
    return ResearchStats(query="test query", urls_searched=3, urls_fetched=2, content_chars=18)


def test_format_json_structure():
    results = _make_results()
    stats = _make_stats()
    output = format_json(results, stats)
    assert output["query"] == "test query"
    assert len(output["content"]) == 2  # only successful
    assert output["content"][0]["url"] == "https://a.com"
    assert "stats" in output


def test_format_json_excludes_failures():
    results = _make_results()
    stats = _make_stats()
    output = format_json(results, stats)
    urls = [r["url"] for r in output["content"]]
    assert "https://b.com" not in urls


def test_format_raw():
    results = _make_results()
    output = format_raw(results)
    assert "=== https://a.com ===" in output
    assert "Content A" in output
    assert "https://b.com" not in output  # failed, skipped


def test_format_markdown():
    results = _make_results()
    stats = _make_stats()
    output = format_markdown(results, stats)
    assert "# Research: test query" in output
    assert "## Page A" in output
    assert "## Page C" in output


def test_format_single_raw():
    r = FetchResult(url="https://x.com", success=True, title="X", content="Hello")
    output = format_result_raw_single(r)
    assert "=== https://x.com ===" in output
    assert "Hello" in output


def test_format_single_json():
    r = FetchResult(url="https://x.com", success=True, title="X", content="Hello")
    output = format_result_json_single(r)
    data = json.loads(output)
    assert data["url"] == "https://x.com"
    assert data["success"] is True
