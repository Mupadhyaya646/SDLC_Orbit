"""Cortex client: runs one agent turn on a registered Cortex agent via ``POST {base}/model/ask/{agent}``.

Cortex owns the agent's prompt, tools and chat history (keyed by ``model_session_id_param``), so this
module only sends the task and returns the final reply text.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

from .config import CortexSettings

logger = logging.getLogger("sdlc_orbit.cortex")

ActivityFn = Callable[[str], Awaitable[None]]


class CortexError(RuntimeError):
    """Cortex rejected the call or returned nothing usable."""


class CortexClient:
    def __init__(self, settings: CortexSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport
        self._access_token: str | None = None
        self._token_expiry = 0.0

    async def _token(self) -> str | None:
        """Static CORTEX_BEARER_TOKEN, else an Azure AD client-credentials token (cached until near expiry)."""
        s = self._s
        if s.bearer:
            return s.bearer
        if not (s.tenant_id and s.client_id and s.client_secret):
            return None
        if self._access_token and time.monotonic() < self._token_expiry:
            return self._access_token
        url = f"https://login.microsoftonline.com/{s.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": s.client_id,
            "client_secret": s.client_secret,
            "scope": s.scope,
        }
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            resp = await client.post(url, data=data)
        if resp.status_code >= 400:
            raise CortexError(f"Azure AD token request failed: HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        self._access_token = body["access_token"]
        self._token_expiry = time.monotonic() + max(60, int(body.get("expires_in", 3600)) - 120)
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        s = self._s
        headers = {"x-user": s.user, **s.extra_headers}
        if s.groups:
            headers["x-groups"] = s.groups
        if s.org:
            headers["x-org"] = json.dumps({"name": s.org})
        token = await self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def ask(self, agent: str, q: str, session_id: str, on_activity: ActivityFn | None = None) -> str:
        url = f"{self._s.base_url}/model/ask/{agent}"
        # (None, value) tuples force multipart/form-data, which /ask requires.
        form = {
            "q": (None, q),
            "stream": (None, "true"),
            "model_session_id_param": (None, session_id),
            "workflow_timeout": (None, str(int(self._s.timeout))),
        }
        headers = await self._headers()
        fragments: list[str] = []
        final: str | None = None
        seen_steps: set[str] = set()
        timeout = httpx.Timeout(self._s.timeout, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            async with client.stream("POST", url, files=form, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    raise CortexError(f"Cortex agent {agent!r}: HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj: Any = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("non-JSON line from Cortex: %.120s", line)
                        continue
                    if not isinstance(obj, dict):
                        continue
                    kind = obj.get("type")
                    if kind == "message":
                        fragments.append(obj.get("message_fragment") or "")
                    elif kind == "step":
                        name = obj.get("name")
                        if on_activity and name and obj.get("status") == "running" and name not in seen_steps:
                            seen_steps.add(name)
                            await on_activity(f"⚙️ {name}")
                    elif kind is None and isinstance(obj.get("message"), str):
                        final = obj["message"]  # server ignored stream=true and sent one JSON document
        text = final if final is not None else "".join(fragments)
        text = _unwrap_final_response(text)
        if not text.strip():
            raise CortexError(f"Cortex agent {agent!r} returned an empty response")
        return text


def _unwrap_final_response(text: str) -> str:
    """Some Cortex agents answer with their ReAct envelope: {"action": "final_response", "message": "..."}."""
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return text
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    if isinstance(obj, dict) and "action" in obj and isinstance(obj.get("message"), str):
        return obj["message"]
    return text
