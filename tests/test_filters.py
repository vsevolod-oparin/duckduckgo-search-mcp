"""Tests for core/filters.py"""
import pytest
from duckduckgo_search_mcp.core.filters import FilterConfig, get_filter_config


def make_cfg() -> FilterConfig:
    cfg = FilterConfig()
    cfg.rebuild_url_pattern()
    return cfg


def test_blocked_domains():
    cfg = make_cfg()
    assert cfg.is_blocked_url("https://reddit.com/r/python") is True
    assert cfg.is_blocked_url("https://twitter.com/user") is True
    assert cfg.is_blocked_url("https://example.com/article") is False


def test_skip_patterns():
    cfg = make_cfg()
    assert cfg.is_blocked_url("https://example.com/category/tech") is True
    assert cfg.is_blocked_url("https://example.com/tag/python") is True
    assert cfg.is_blocked_url("https://example.com/page/2") is True
    assert cfg.is_blocked_url("https://example.com/article/my-post") is False


def test_captcha_detection():
    cfg = make_cfg()
    blocked_html = "Please verify you are human to continue."
    normal_html  = "Welcome to our website. Here is the article."
    assert cfg.is_blocked_content(blocked_html) is True
    assert cfg.is_blocked_content(normal_html)  is False


def test_custom_domain_blocking():
    cfg = make_cfg()
    cfg.blocked_domains.append("example.com")
    cfg.rebuild_url_pattern()
    assert cfg.is_blocked_url("https://example.com/anything") is True
    assert cfg.is_blocked_url("https://other.com/anything") is False


def test_empty_content_not_blocked():
    cfg = make_cfg()
    assert cfg.is_blocked_content("") is False
    assert cfg.is_blocked_content("hi") is False


def test_navigation_line():
    cfg = make_cfg()
    assert cfg.is_navigation_line("Skip to main content") is True
    assert cfg.is_navigation_line("Jump to navigation") is True
    assert cfg.is_navigation_line("This is an article paragraph.") is False
