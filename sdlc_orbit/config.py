"""Environment-driven settings. Nothing here reads a secret from a file; every
credential arrives as an environment variable (in CATS: mounted from the
``ExternalSecret`` that wraps AWS Secrets Manager).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, *fallbacks: str, default: str | None = None) -> str | None:
    for n in (name, *fallbacks):
        v = os.getenv(n)
        if v:
            return v
    return default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def database_dsn() -> str:
    """DATABASE_URL (local dev) or a DSN composed from the four separate keys a
    Crossplane ``PostgresClaim`` connection secret exposes."""
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return dsn
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USERNAME")
    password = os.getenv("POSTGRES_PASSWORD")
    dbname = os.getenv("POSTGRES_DB_NAME", "postgres")
    if not (host and user and password):
        raise RuntimeError(
            "Set either DATABASE_URL, or all of POSTGRES_HOST / POSTGRES_USERNAME / "
            "POSTGRES_PASSWORD (POSTGRES_PORT and POSTGRES_DB_NAME are optional)."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


# ---------------------------------------------------------------------------
# LLM (Anthropic)
# ---------------------------------------------------------------------------


# Latest Claude generation (Anthropic model docs): Opus 5.5 and Sonnet 5.5. Override with
# LLM_MODEL_OPUS / LLM_MODEL_SONNET (or LLM_MODEL for both) -- e.g. "claude-fable-5-1" for the
# most capable (slower, ~2.5x the price) or "claude-haiku-5-5" for the lowest latency.
DEFAULT_MODEL_OPUS = "claude-opus-5-5"
DEFAULT_MODEL_SONNET = "claude-sonnet-5-5"


@dataclass(frozen=True)
class LlmSettings:
    model_opus: str  # "opus-tier" agents (design, review, devops, commit, docs, unit-test)
    model_sonnet: str  # "sonnet-tier" agents (admin, developer)
    api_key: str
    base_url: str | None  # optional: an Anthropic-compatible gateway
    # None => not sent. Adaptive thinking is always on for the 5.5 models and sampling
    # parameters can conflict with thinking, so temperature is opt-in.
    temperature: float | None
    max_tokens: int
    request_timeout: float
    extra_headers: dict[str, str] = field(default_factory=dict)  # e.g. gateway "x-application-id"


def _parse_headers(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def llm_settings() -> LlmSettings:
    """Validated at startup so a misconfiguration fails fast instead of mid-run."""
    api_key = _env("ANTHROPIC_API_KEY", "LLM_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY (or LLM_API_KEY) must be set.")
    both = _env("LLM_MODEL")  # optional: one model for every agent
    raw_temp = os.getenv("LLM_TEMPERATURE")
    return LlmSettings(
        model_opus=_env("LLM_MODEL_OPUS", default=both or DEFAULT_MODEL_OPUS) or DEFAULT_MODEL_OPUS,
        model_sonnet=_env("LLM_MODEL_SONNET", default=both or DEFAULT_MODEL_SONNET) or DEFAULT_MODEL_SONNET,
        api_key=api_key,
        base_url=_env("ANTHROPIC_BASE_URL", "LLM_BASE_URL"),
        temperature=float(raw_temp) if raw_temp else None,
        max_tokens=_int("LLM_MAX_TOKENS", 16000),
        request_timeout=_float("LLM_REQUEST_TIMEOUT_SECONDS", 300.0),
        extra_headers=_parse_headers(_env("LLM_EXTRA_HEADERS")),
    )


@dataclass(frozen=True)
class CortexSettings:
    base_url: str
    user: str  # x-user (email)
    groups: str  # x-groups (comma separated)
    org: str  # x-org -> {"name": org}
    bearer: str | None  # optional gateway token -> Authorization: Bearer
    extra_headers: dict[str, str] = field(default_factory=dict)  # e.g. x-application-id
    timeout: float = 1800.0
    # Azure AD client-credentials app; the gateway needs its token as Authorization: Bearer.
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str = "api://Cortex.lilly.com/.default"


DEFAULT_CORTEX_BASE_URL = "https://gateway.apim.lilly.com/cortex"


def cortex_settings() -> CortexSettings | None:
    """None unless ``LLM_PROVIDER=cortex``. Then the registered Cortex agents (by ``agent_id``)
    run each turn and no Anthropic key is needed."""
    if (_env("LLM_PROVIDER", default="anthropic") or "").lower() != "cortex":
        return None
    user = _env("CORTEX_USER")
    if not user:
        raise RuntimeError("LLM_PROVIDER=cortex requires CORTEX_USER (the x-user email sent to Cortex).")
    return CortexSettings(
        base_url=(_env("CORTEX_BASE_URL", default=DEFAULT_CORTEX_BASE_URL) or DEFAULT_CORTEX_BASE_URL).rstrip("/"),
        user=user,
        groups=_env("CORTEX_GROUPS", default="") or "",
        org=_env("CORTEX_ORG", default="") or "",
        bearer=_env("CORTEX_BEARER_TOKEN"),
        extra_headers=_parse_headers(_env("CORTEX_EXTRA_HEADERS")),
        timeout=_float("CORTEX_TIMEOUT_SECONDS", 1800.0),
        tenant_id=_env("AZURE_TENANT_ID"),
        client_id=_env("AZURE_CLIENT_ID"),
        client_secret=_env("AZURE_CLIENT_SECRET"),
        scope=_env("CORTEX_SCOPE", default="api://Cortex.lilly.com/.default") or "api://Cortex.lilly.com/.default",
    )


# ---------------------------------------------------------------------------
# MCP toolkit servers (Lane 4)
# ---------------------------------------------------------------------------

_NS = os.getenv("ORBIT_K8S_NAMESPACE", "sdlc-orbit-dev")


@dataclass(frozen=True)
class McpEndpoints:
    confluence: str
    salesforce: str  # org where admin / developer / unit-testing agents work
    salesforce_qa: str  # devops stage 1 (QA); falls back to ``salesforce``
    salesforce_prod: str | None  # devops stage 2 (Prod); NO fallback -- fail closed
    gitops: str
    # Optional static bearer for the MCP servers (they have no auth of their own today;
    # in-cluster DNS only, no ingress). Reserved for a future gateway.
    bearer: str | None


def mcp_endpoints() -> McpEndpoints:
    def url(var: str, host: str, port: int) -> str:
        return _env(var, default=f"http://{host}.{_NS}.svc.cluster.local:{port}/mcp") or ""

    sf = url("MCP_SALESFORCE_URL", "salesforce-mcp", 6000)
    return McpEndpoints(
        confluence=url("MCP_CONFLUENCE_URL", "confluence-mcp", 6001),
        salesforce=sf,
        salesforce_qa=_env("MCP_SALESFORCE_QA_URL", default=sf) or sf,
        salesforce_prod=_env("MCP_SALESFORCE_PROD_URL"),
        gitops=url("MCP_GITOPS_URL", "gitops-mcp", 6002),
        bearer=_env("MCP_BEARER_TOKEN"),
    )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeSettings:
    env: str  # dev | prod
    max_rework_loops: int  # develop-phase rework cap before the G6 escalation gate
    recursion_limit: int
    sse_poll_seconds: float
    sse_heartbeat_seconds: float
    sse_retry_ms: int
    identity_mode: str  # auto | header | dev
    identity_header: str | None
    identity_strict: bool
    db_pool_max: int


def runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        env=(_env("ORBIT_ENV", default="dev") or "dev").lower(),
        max_rework_loops=_int("ORBIT_MAX_REWORK_LOOPS", 3),
        recursion_limit=_int("ORBIT_RECURSION_LIMIT", 200),
        sse_poll_seconds=_float("SSE_POLL_INTERVAL_SECONDS", 0.5),
        sse_heartbeat_seconds=_float("SSE_HEARTBEAT_INTERVAL_SECONDS", 25.0),
        sse_retry_ms=_int("SSE_RETRY_DELAY_MS", 8000),
        identity_mode=(_env("IDENTITY_MODE", default="auto") or "auto").lower(),
        identity_header=_env("IDENTITY_HEADER"),
        identity_strict=_bool("IDENTITY_STRICT", False),
        db_pool_max=_int("DB_POOL_MAX", 10),
    )
