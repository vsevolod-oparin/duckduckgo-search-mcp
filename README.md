# DuckDuckGo Web Search MCP

**NOTE: This MCP is a vibe-coded translation of https://github.com/itohnobue/web_search_agent.**

Generic web research MCP server built on top of DuckDuckGo + httpx.

## Tools

| Tool | Description |
|------|-------------|
| `search_web` | DuckDuckGo search → `[{url, title}]` |
| `fetch_page` | Fetch + extract a single URL |
| `research` | Full search + parallel fetch pipeline (cached) |
| `_update_filters` | Update filter lists at runtime (management) |
| `_cache_clear` | Clear all cached results (management) |
| `_cache_stats` | Show cache statistics (management) |

## Prompts

| Prompt | Description |
|--------|-------------|
| `research_report` | Template for synthesising research results into a structured report |

## Resources

| URI | Description |
|-----|-------------|
| `filters://blocked-domains` | Readable list of blocked domains |
| `filters://skip-url-patterns` | Readable list of skip URL regex patterns |
| `filters://blocked-content` | Readable CAPTCHA detection markers |
| `cache://stats` | Read-only cache statistics |

## Installation

```bash
# Clone and install
git clone <repo>
cd web-search-mcp
uv sync
```

## Running

```bash
uv run web-search-mcp
```

## MCP Client Configuration

Add to your `claude_desktop_config.json` (or equivalent):

```json
{
  "mcpServers": {
    "web-search": {
      "command": "uv",
      "args": ["--directory", "/path/to/web-search-mcp", "run", "web-search-mcp"]
    }
  }
}
```

## Optional Extensions

### Redis Cache

Set `REDIS_URL` to enable cross-session result caching:

```bash
REDIS_URL=redis://localhost:6379/0 uv run web-search-mcp
```

| Env var | Default | Description |
|---------|---------|-------------|
| `REDIS_URL` | *(empty)* | Redis URL; if absent, memory-only |
| `CACHE_TTL_MEM` | `3600` | In-memory TTL (seconds) |
| `CACHE_TTL_REDIS` | `21600` | Redis TTL (seconds) |
| `CACHE_MAX_SIZE` | `128` | Max in-memory entries |
| `LOG_LEVEL` | `WARNING` | Logging level |

Install Redis support:

```bash
uv add redis
```

### Runtime Filter Updates

Use the `_update_filters` tool to extend or replace filter lists without restarting:

```json
{
  "name": "_update_filters",
  "arguments": {
    "blocked_domains": ["reddit.com", "twitter.com", "mysite.com"]
  }
}
```

## Development

```bash
uv sync --extra dev
uv run pytest tests/ -v
```

## Architecture

```
web_search_mcp/
├── server.py              # MCP server: tools, resources, prompts
├── core/
│   ├── config.py          # ResearchConfig, FetchResult, ResearchStats
│   ├── filters.py         # URL + content filtering (runtime-configurable)
│   ├── extractor.py       # HTML → clean text
│   ├── fetcher.py         # Async HTTP/2 page fetcher
│   ├── ddg.py             # DuckDuckGo search wrapper
│   ├── pipeline.py        # Async search+fetch producer/consumer pipeline
│   ├── formatters.py      # JSON / raw / markdown output formatters
│   └── cache.py           # Two-tier cache (memory + optional Redis)
├── tools/
│   ├── search.py          # search_web handler
│   ├── fetch.py           # fetch_page handler
│   └── research.py        # research handler
└── prompts/
    └── research_report.md # Report synthesis prompt template
```
