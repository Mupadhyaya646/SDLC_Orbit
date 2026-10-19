"""Who answered a gate? Resolved by the API layer, never by an agent.

The architecture requires every gate answer to carry a *verified* human
identity stamped by the API / webhook layer -- "never from the request body or
agent output". In CATS the app sits behind the platform ALB, which injects the
authenticated user into request headers, so identity is read from headers.

Fail-open vs fail-closed: a previous deployment of this tool shipped a
token gate that locked every user out because nobody could retrieve the secret.
So the default (``IDENTITY_STRICT=false``) never blocks a reply: when no header
identity is present the answer is recorded as ``unverified:<name from body>``
so the audit trail shows exactly which answers lack a verified identity.
Set ``IDENTITY_STRICT=true`` once the header is confirmed to flow through.

NOTE: the ALB OIDC JWT (``x-amzn-oidc-data``) is decoded WITHOUT signature
verification. That is only safe because the service is reachable solely through
the ALB / in-cluster; verify the signature if the pod is ever exposed otherwise.
"""
from __future__ import annotations

import base64
import json
from typing import Mapping


class IdentityError(Exception):
    """No identity could be established and strict mode is on."""


_JWT_CLAIMS = ("email", "preferred_username", "upn", "unique_name", "name", "sub")
_PLAIN_HEADERS = (
    "x-auth-request-email",
    "x-forwarded-email",
    "x-ms-client-principal-name",
    "x-forwarded-preferred-username",
    "x-forwarded-user",
)


def _decode_jwt_identity(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:  # noqa: BLE001 - malformed token => no identity, never an error
        return None
    for key in _JWT_CLAIMS:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def identity_from_headers(headers: Mapping[str, str], configured_header: str | None = None) -> str | None:
    lowered = {k.lower(): v for k, v in headers.items()}
    if configured_header:
        value = (lowered.get(configured_header.lower()) or "").strip()
        if value:
            # A configured header may itself carry a JWT.
            return (_decode_jwt_identity(value) if value.count(".") == 2 else None) or value
    token = (lowered.get("x-amzn-oidc-data") or "").strip()
    if token:
        found = _decode_jwt_identity(token)
        if found:
            return found
    for name in _PLAIN_HEADERS:
        value = (lowered.get(name) or "").strip()
        if value:
            return value
    return None


def resolve_identity(
    headers: Mapping[str, str],
    body_answered_by: str | None,
    *,
    mode: str = "auto",
    configured_header: str | None = None,
    strict: bool = False,
) -> str:
    """Return the identity to stamp on a gate answer.

    mode "auto"/"header": headers first, then (non-strict) ``unverified:<body>``.
    mode "dev": the body value (or "dev-user"); for local development only.
    """
    if mode == "dev":
        return (body_answered_by or "").strip() or "dev-user"
    verified = identity_from_headers(headers, configured_header)
    if verified:
        return verified
    if strict:
        raise IdentityError("no authenticated identity header present on this request")
    claimed = (body_answered_by or "").strip() or "unknown"
    return f"unverified:{claimed}"
