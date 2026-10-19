# confluence-mcp

> **Migration note (SDLC_Orbit).** This server is unchanged by the move from the Cortex-orchestrated
> Felix pipeline to the LangGraph-based SDLC_Orbit. Mentions of Felix / Helix / Cortex below describe the
> previous orchestrator. Kubernetes names such as `felix-dev` and `felix-dev-secrets` are the names currently
> deployed in the infra repo, so they are intentionally left as-is until that repo is renamed. The agents now
> reach this server over streamable HTTP at `/mcp` via `langchain-mcp-adapters` (see `sdlc_orbit/mcp_tools.py`),
> not through a Cortex toolkit registration (the `toolkits/*.json` files are no longer used).


A real Confluence MCP server, following the exact pattern of the sibling `jira/` toolkit in
`Hive-Core/toolkits/`: FastMCP (`mcp.server.fastmcp`), one `@mcp.tool()` per exposed tool, a
`ConfluenceToolBase` shared auth/HTTP helper, and a plain `/healthz` HTTP route added to
FastMCP's underlying Starlette app for k8s probes (FastMCP's `streamable-http` transport has no
bare HTTP health route of its own — only the MCP protocol — so without this the k8s
liveness/readiness probes in `deploy-confluence-mcp.yaml` would 404 forever).

Replaces the original local tool's `@devpuccino/mcp-confluence` npx/stdio package (built for
local Claude Code use, not a long-running hosted service) with a native implementation against
Confluence Cloud's real REST API, exposing the **same 4 tool names** the already-ported
`salesforce-design-agent.json` / `salesforce-documentation-agent.json` Cortex configs expect:
`search_content`, `get_page`, `update_page`, `get_current_user`.

## Tools

| Tool | Confluence API used | Notes |
|---|---|---|
| `search_content` | v1 `GET /wiki/rest/api/content/search?cql=...` | CQL search has no v2 equivalent yet |
| `get_page` | v2 `GET /wiki/api/v2/pages/{id}` | current recommended API for page reads |
| `update_page` | v2 `PUT /wiki/api/v2/pages/{id}` | optimistic-locked via `version.number + 1`; caller supplies the FULL new body — this tool does not construct the modified XHTML itself |
| `get_current_user` | v1 `GET /wiki/rest/api/user/current` | still the standard way to resolve the authenticated identity |

## Env vars (must match `deploy-confluence-mcp.yaml` / `external-secrets.yaml` exactly — confirmed, not guessed)

| Var | Source in CATS | Notes |
|---|---|---|
| `PORT` | plain env, `"6001"` | matches the Deployment's `containerPort` |
| `CONFLUENCE_DOMAIN` | plain env, `"lilly-confluence.atlassian.net"` | Atlassian Cloud instance |
| `CONFLUENCE_EMAIL` | `felix-dev-secrets` secret | Basic Auth username half |
| `CONFLUENCE_API_TOKEN` | `felix-dev-secrets` secret | Basic Auth password half |

Auth: `Authorization: Basic base64(CONFLUENCE_EMAIL:CONFLUENCE_API_TOKEN)` — identical
construction to the sibling Jira toolkit's `_auth_header()`, since Jira and Confluence Cloud
share the same Atlassian Cloud auth mechanism.

## Run locally

```
cp .env.example .env   # fill in real CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN
pip install -r requirements.txt
python -m app.server
```

Or via the MCP inspector (same pattern as the Jira toolkit):
```
make setup   # run twice, per the Makefile's own note
make server
```

Health check once running:
```
curl http://localhost:6001/healthz
```

## Not run/verified in this environment

No Docker daemon and no outbound network access to PyPI/Artifactory were available while
building this — `mcp`/`fastapi`/`uvicorn` were never actually installed or run here. Verified
instead via `python3 -m py_compile` on every `.py` file (all pass), and the `/healthz` Starlette
route-append pattern was independently confirmed against a real `starlette.testclient.TestClient`
(Starlette itself IS installed in this sandbox, unlike `mcp`/`fastapi`). A real build/run must
happen in Lilly's own CI/cluster before trusting this image.
