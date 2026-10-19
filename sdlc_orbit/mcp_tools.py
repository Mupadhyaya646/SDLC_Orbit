"""Lane 4 client: loads LangChain tools from the in-cluster MCP toolkit servers.

* One streamable-HTTP connection config per server key.
* Tools are fetched lazily and cached per server key for the process lifetime;
  a failed fetch is NOT cached, so a toolkit pod that was down at startup is
  picked up on the next agent turn.
* Each agent is handed only its allow-listed tools (least privilege).
* The Prod Salesforce server has no fallback: if ``MCP_SALESFORCE_PROD_URL`` is
  unset the devops Prod stage fails closed with a clear error.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any

from .agents import (
    SRV_CONFLUENCE,
    SRV_GITOPS,
    SRV_SALESFORCE,
    SRV_SALESFORCE_PROD,
    SRV_SALESFORCE_QA,
)
from .config import McpEndpoints, mcp_endpoints

logger = logging.getLogger("sdlc_orbit.mcp")

# Long-running tools (validate-only deploys with test runs) can be silent on the
# stream for minutes; the adapters' 300s default read timeout is too tight.
_TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "900"))
_CONNECT_TIMEOUT_SECONDS = float(os.getenv("MCP_CONNECT_TIMEOUT_SECONDS", "30"))


class McpUnavailable(RuntimeError):
    """A required toolkit server is not configured or not reachable."""


class McpToolRegistry:
    def __init__(self, endpoints: McpEndpoints | None = None) -> None:
        self._ep = endpoints or mcp_endpoints()
        self._clients: dict[str, Any] = {}
        self._cache: dict[str, list[Any]] = {}
        self._lock = asyncio.Lock()

    # -- configuration -----------------------------------------------------

    def url_for(self, server: str) -> str:
        ep = self._ep
        url = {
            SRV_CONFLUENCE: ep.confluence,
            SRV_SALESFORCE: ep.salesforce,
            SRV_SALESFORCE_QA: ep.salesforce_qa,
            SRV_SALESFORCE_PROD: ep.salesforce_prod,
            SRV_GITOPS: ep.gitops,
        }.get(server)
        if not url:
            raise McpUnavailable(
                f"MCP server '{server}' is not configured"
                + (" (set MCP_SALESFORCE_PROD_URL; Prod has no fallback by design)" if server == SRV_SALESFORCE_PROD else "")
            )
        return url

    def _connection(self, server: str) -> dict[str, Any]:
        conn: dict[str, Any] = {
            "url": self.url_for(server),
            "transport": "streamable_http",
            "timeout": timedelta(seconds=_CONNECT_TIMEOUT_SECONDS),
            "sse_read_timeout": timedelta(seconds=_TOOL_TIMEOUT_SECONDS),
        }
        if self._ep.bearer:
            conn["headers"] = {"Authorization": f"Bearer {self._ep.bearer}"}
        return conn

    def _get_client(self, server: str):
        # Import lazily so unit tests that never touch MCP don't need the dependency.
        from langchain_mcp_adapters.client import MultiServerMCPClient

        # One client per server keeps an unreachable toolkit from blocking the others.
        client = self._clients.get(server)
        if client is None:
            client = MultiServerMCPClient({server: self._connection(server)})
            self._clients[server] = client
        return client

    # -- tool access -------------------------------------------------------

    async def tools_for(self, server: str | None, allow: tuple[str, ...]) -> list[Any]:
        """The allow-listed tools of ``server`` (empty list when no server)."""
        if not server or not allow:
            return []
        async with self._lock:
            tools = self._cache.get(server)
            if tools is None:
                try:
                    tools = await self._get_client(server).get_tools(server_name=server)
                except McpUnavailable:
                    raise
                except Exception as exc:  # noqa: BLE001 - surface as one clear error type
                    raise McpUnavailable(f"could not load tools from MCP server '{server}' ({self.url_for(server)}): {exc}") from exc
                self._cache[server] = tools
                logger.info("loaded %d tools from %s: %s", len(tools), server, sorted(t.name for t in tools))
        by_name = {t.name: t for t in tools}
        missing = [n for n in allow if n not in by_name]
        if missing:
            # Fail loudly: an agent silently missing a tool it is prompted to call
            # would improvise or stall.
            raise McpUnavailable(f"MCP server '{server}' does not expose required tool(s): {missing}")
        return [by_name[n] for n in allow]

    def forget(self, server: str) -> None:
        """Drop cached tools for ``server`` (e.g. after a connection error)."""
        self._cache.pop(server, None)

    async def health(self) -> dict[str, str]:
        """Best-effort reachability report for /readyz (never raises)."""
        report: dict[str, str] = {}
        for server in (SRV_CONFLUENCE, SRV_SALESFORCE, SRV_SALESFORCE_QA, SRV_SALESFORCE_PROD, SRV_GITOPS):
            try:
                self.url_for(server)
            except McpUnavailable as exc:
                report[server] = f"not configured: {exc}"
                continue
            try:
                await asyncio.wait_for(self._get_client(server).get_tools(server_name=server), timeout=15)
                report[server] = "ok"
            except Exception as exc:  # noqa: BLE001
                report[server] = f"unreachable: {type(exc).__name__}: {exc}"
        return report


_registry: McpToolRegistry | None = None


def get_registry() -> McpToolRegistry:
    global _registry
    if _registry is None:
        _registry = McpToolRegistry()
    return _registry
