from __future__ import annotations

from typing import Any


def create_server() -> Any:
    from mcp.server.fastmcp import FastMCP

    return FastMCP("peoplebooks-mcp")
