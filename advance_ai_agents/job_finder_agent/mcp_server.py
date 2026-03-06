import os
from agents.mcp import MCPServerStdio


def make_websearch_mcp_server() -> MCPServerStdio:
    """Create a WebSearch MCP server instance for web search.
    Requires the crawler Docker service running locally.
    Set WEBSEARCH_API_URL (default: http://localhost:3001)."""
    api_url = os.environ.get("WEBSEARCH_API_URL", "http://localhost:3001")
    return MCPServerStdio(
        cache_tools_list=True,
        client_session_timeout_seconds=120,
        params={
            "command": "npx",
            "args": ["websearch-mcp"],
            "env": {
                "API_URL": api_url,
            },
        },
    )


def make_firecrawl_mcp_server() -> MCPServerStdio:
    """Create a Firecrawl MCP server instance for web search and scraping.
    Requires FIRECRAWL_API_KEY environment variable.
    Get your key at https://firecrawl.dev"""
    api_key = os.environ["FIRECRAWL_API_KEY"]
    return MCPServerStdio(
        cache_tools_list=True,
        client_session_timeout_seconds=120,
        params={
            "command": "npx",
            "args": ["-y", "firecrawl-mcp"],
            "env": {
                "FIRECRAWL_API_KEY": api_key,
            },
        },
    )


def make_search_mcp_server() -> MCPServerStdio:
    """Select search MCP provider based on SEARCH_PROVIDER env var.

    SEARCH_PROVIDER=websearch  — cheap, requires Docker (default)
    SEARCH_PROVIDER=firecrawl  — higher quality, requires FIRECRAWL_API_KEY
    """
    provider = os.environ.get("SEARCH_PROVIDER", "websearch").lower()
    if provider == "firecrawl":
        return make_firecrawl_mcp_server()
    return make_websearch_mcp_server()
