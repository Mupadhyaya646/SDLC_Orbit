# salesforce-mcp

> **Migration note (SDLC_Orbit).** This server is unchanged by the move from the Cortex-orchestrated
> Felix pipeline to the LangGraph-based SDLC_Orbit. Mentions of Felix / Helix / Cortex below describe the
> previous orchestrator. Kubernetes names such as `felix-dev` and `felix-dev-secrets` are the names currently
> deployed in the infra repo, so they are intentionally left as-is until that repo is renamed. The agents now
> reach this server over streamable HTTP at `/mcp` via `langchain-mcp-adapters` (see `sdlc_orbit/mcp_tools.py`),
> not through a Cortex toolkit registration (the `toolkits/*.json` files are no longer used).


MCP server for Salesforce declarative metadata operations. Built to match the Cortex
`salesforce-mcp-toolkit` registration (`../salesforce-mcp.json`) and the exact tool names/
descriptions the ported agent configs expect — see
`/Users/L072390/Library/CloudStorage/OneDrive-EliLillyandCompany/Helix/helix-cortex-backend/agents/
salesforce-admin-agent.json`, `salesforce-developer-agent.json`,
`salesforce-unit-testing-agent.json`, `salesforce-devops-agent.json`.

Structure mirrors the confirmed-working `jira` toolkit at
`Hive-Core/toolkits/jira/` — same `app/server.py` + `app/<domain>/base.py` + one-module-per-tool
layout, same logger/middleware, same Dockerfile shape.

## Tools exposed

| Tool | Used by | What it does |
|---|---|---|
| `sf_describe_object` | admin, developer, unit-testing | `/describe` an sObject's fields/relationships |
| `sf_read_metadata` | admin, developer, unit-testing | Look up an existing CustomField/ValidationRule/PermissionSet/Flow by name |
| `sf_write_metadata` | admin, developer, unit-testing | Create/update one metadata component via the Tooling API |
| `sf_deploy_metadata` | devops | Deploy up to 10 components (loops `sf_write_metadata`) |
| `sf_deploy_validate` | devops | Check-only deploy for larger manifests (Apex/LWC/multi-component) via the `sf` CLI |

## Auth: Salesforce OAuth2 username-password flow

Chosen over JWT bearer flow because it needs no certificate/keypair management — just an
integration user + a connected app, both already standard at most orgs. `app/salesforce/base.py`
requests a token from `{SF_LOGIN_URL}/services/oauth2/token` and caches it in-process for 30
minutes (re-authenticates automatically on a 401).

### Required environment variables

| Var | Notes |
|---|---|
| `SF_LOGIN_URL` | e.g. `https://login.salesforce.com`, or your org's My Domain URL |
| `SF_USERNAME` | integration user's username |
| `SF_PASSWORD` | integration user's password |
| `SF_SECURITY_TOKEN` | integration user's security token (Setup → My Personal Information → Reset My Security Token) |
| `SF_CLIENT_ID` | connected app consumer key |
| `SF_CLIENT_SECRET` | connected app consumer secret |
| `SF_API_VERSION` | optional, defaults to `61.0` |
| `PORT` | optional, defaults to `6000` (matches `deploy-salesforce-mcp.yaml`) |

**Resolved:** `LRL_light_k8s_infra_apps_test/projects/dev/felix-dev/deploy-salesforce-mcp.yaml`
now wires all 6 `SF_*` env vars from `felix-dev-secrets`, and `felix-dev-salesforce-creds` in
AWS Secrets Manager needs all 6 properties populated (`username`, `login_url`, `password`,
`security_token`, `client_id`, `client_secret`).


## The `sf` CLI dependency (sf_deploy_validate only)

`sf_deploy_validate` shells out to `sf project deploy validate` rather than hand-rolling a
Metadata API SOAP `deploy()` call — the ZIP packaging / `checkDeployStatus` polling loop a
correct from-scratch implementation needs is substantial, and the CLI already does this
correctly. The Dockerfile installs Node.js + `@salesforce/cli` for this reason. The tool logs
into the CLI per-request using the same OAuth2 access token `SalesforceToolBase` already
obtained (`sf org login access-token`) — no separate CLI-specific credential needed. If the `sf`
CLI isn't installed (e.g. a slimmed-down image rebuild drops it), `sf_deploy_validate` returns
`success: false, error_type: "EnvironmentError"` rather than crashing.

## `sf_write_metadata`'s JSON-not-XML choice

Accepts the Tooling API's REST JSON shape (e.g. `{"Metadata": {"label": "...", "type": "Text"}}`),
not raw Metadata API XML — this is a deliberate simplification. The Tooling API lets a single
component be created/updated with one plain JSON POST/PATCH; building a full Metadata API deploy
ZIP for one field at a time would be substantially more code for no benefit at this scale (that
heavier path IS used, via the `sf` CLI, for `sf_deploy_validate`'s larger manifests).

## Run locally

```
pip install -r requirements.txt
export SF_LOGIN_URL=https://login.salesforce.com SF_USERNAME=... SF_PASSWORD=... \
       SF_SECURITY_TOKEN=... SF_CLIENT_ID=... SF_CLIENT_SECRET=...
python -m app.server
```

Health check: `curl http://localhost:6000/healthz`

## Not verified by an actual run

No `mcp`/`fastapi`/`requests` packages installed in the environment this was built in (no
outbound network access) — only checked via `python3 -m py_compile` on every `.py` file (all
pass). No real Salesforce org credentials were available to test the OAuth2 flow or any Tooling
API call end-to-end. A real test against a sandbox org is needed before trusting this in
production.
