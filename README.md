# SDLC_Orbit

LangGraph orchestration of the eight Salesforce SDLC specialist agents. It replaces the Cortex-orchestrated
**Felix** pipeline: the agents now call a model and the in-cluster MCP toolkit servers directly, inside a
supervisor `StateGraph` with durable Postgres checkpoints and human gates implemented as graph interrupts.

> **Status: first cut, not yet run end-to-end.** The pure logic (gate detection, parsers, identity, view
> derivation) has unit tests that pass. The LangGraph flow tests (`tests/test_graph.py`) were written but have
> **not been executed** (the authoring environment had no Artifactory access). Run them first (see *Verify*).
> ServiceNow / CHG lifecycle is intentionally **not** implemented.

## What changed from Felix

| | Felix (Cortex) | SDLC_Orbit (LangGraph) |
|---|---|---|
| Agent call | blocking `POST /model/ask` per step, one request thread held for the whole turn | direct model + MCP tool loop; runs are background tasks, the API returns at once, progress streams over SSE |
| Sequencing | hand-written state machine in `pipeline.py` | deterministic supervisor `StateGraph` (`sdlc_orbit/graph.py`) |
| Pausing at a gate | regex on every reply, state in a JSONB column | a pure `gate_wait` node calling `interrupt()`; state in Postgres checkpoints (`thread_id = session_id`) |
| Agent context | each agent in an isolated Cortex session (never saw earlier agents' output) | prior outputs are supplied as `SESSION CONTEXT` (what the prompts always assumed) |
| Order | design, admin/dev, test, review, deploy, pre-launch, commit + docs in parallel | design, admin, developer, test, review, **commit/PR**, QA deploy, G2, G3, G4, merge, Prod deploy, G5, docs (per the architecture diagram) |
| Prompts | Cortex agent JSONs | `sdlc_orbit/prompts/*.md`: bodies verbatim; only the Cortex scaffolding was replaced |

## Flow

```
design -> [design_confirm] -> admin -> developer -> unit_testing -> code_review
   code_review -- CHANGES REQUIRED --> developer   (automatic, capped at ORBIT_MAX_REWORK_LOOPS, then G6)
   code_review -- approved ----------> github_commit (6 internal human gates)
   -> qa_deploy -> qa_confirm (G2) -> uat_approval (G3) -> pr_approval (G4) -> merge_confirm
   -> prod_preflight (deterministic guard) -> prod_deploy -> prod_confirm (G5; "incorrect" -> G6)
   -> docs_preflight -> documentation -> finish
Any human "fix" (QA / UAT / PR / hotfix) repeats: developer -> unit_testing -> code_review -> commit -> QA -> G2 -> G3.
```

Gate letters: `Y` yes/approved, `C` cancel, `R` reject/retry, `F` fix, `M` merged, `H` hotfix. An unrecognised
answer **re-asks the same gate**; only an explicit `C` cancels.

### Safety invariants (enforced in code, covered by tests)

- Agents never answer gates. `gate_wait` accepts only a payload stamped by the API/webhook layer with a
  non-empty identity and the matching gate id; anything else raises.
- `answered_by` comes from authenticated headers, never from the request body (see *Identity*).
- Least privilege: each agent gets only its allow-listed MCP tools (`sdlc_orbit/agents.py`). Only the devops
  agent can deploy; the design agent never sees a Salesforce tool.
- Prod fails closed: `MCP_SALESFORCE_PROD_URL` has no default, and `prod_preflight` refuses to continue unless
  QA confirm, UAT, PR approval and merge are each on record with a human identity and UAT is still valid.
- Anything that changes code after UAT invalidates UAT; the QA and UAT gates are asked again.
- Gate detection runs only on the four agents that can raise gates (design, commit, devops, documentation),
  because Apex like `accounts[0]` would otherwise look like an option token.
- An unrecognised code-review verdict is treated as CHANGES REQUIRED, never as approval.

## Configuration

See `.env.example`. The essentials:

- `DATABASE_URL`, or `POSTGRES_HOST/PORT/USERNAME/PASSWORD` (Crossplane claim keys).
- `ANTHROPIC_API_KEY`. Models default to the latest generation: `claude-opus-5-5` for design, review, devops,
  commit, docs and unit-testing, and `claude-sonnet-5-5` for admin and developer (the tiers preserved from the
  Cortex registrations). Override with `LLM_MODEL_OPUS` / `LLM_MODEL_SONNET`, or `LLM_MODEL` for both:
  `claude-fable-5-1` is the most capable but slower and about 2.5x the price; `claude-haiku-5-5` is the fastest.
  Moving more agents to the faster tier is the main latency lever. `ANTHROPIC_BASE_URL` / `LLM_EXTRA_HEADERS`
  support a gateway. `temperature` is not sent unless `LLM_TEMPERATURE` is set (adaptive thinking is always on).
  **Do not change model ids while sessions are mid-run**: thinking blocks are tied to the model that wrote them.
- `MCP_*_URL` or `ORBIT_K8S_NAMESPACE`. Defaults point at `*.sdlc-orbit-dev.svc.cluster.local`, but the infra
  repo still deploys the toolkits to `felix-dev`: rename it there, or set the URLs explicitly.
- `IDENTITY_*`: see below.

### Identity

Gate answers are stamped from request headers (`x-amzn-oidc-data` JWT, `x-forwarded-email`, ... or
`IDENTITY_HEADER`). By default (`IDENTITY_STRICT=false`) a reply with no verified header is still accepted but
recorded as `unverified:<name>`, so a wrong header assumption cannot lock everyone out (the previous deployment
had exactly that failure with a token gate). Check the Journal tab after the first run: if names show as
`unverified:you`, the header is not flowing; fix that, then set `IDENTITY_STRICT=true`.
The ALB JWT is decoded **without** signature verification, which is only safe because the pod is reachable
solely through the ALB.

## Run locally

Packages come from Lilly's Artifactory only (public PyPI / npm are prohibited); configure pip first
(see the `lilly-artifactory` skill / <https://dev.lilly.com/docs/platforms-and-tools/artifactory/>).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in, then: set -a; source .env; set +a
uvicorn sdlc_orbit.api.main:app --reload --port 8000
# dashboard dev server (proxies /api to :8000):
cd frontend && npm ci && npm run dev
```

The three MCP toolkit servers live in `toolkits/` (unchanged; each has its own README and Dockerfile).

## Verify (do this first)

1. `python -m unittest discover -s tests -v`: gates / identity / view run anywhere; `test_graph.py` needs the
   dependencies and is the first real proof of the LangGraph wiring.
2. `GET /readyz`: database plus a reachability report for each MCP server.
3. Start a session with a small request in dev and watch it reach `design_confirm`. Confirm the Journal tab
   shows your real identity.
4. Walk one change to QA before touching Prod. Leave `MCP_SALESFORCE_PROD_URL` unset until you intend to deploy
   to Prod; the run will stop at a `tools_unavailable` gate instead.

## API

Unchanged from Felix: `POST /api/sessions`, `GET /api/sessions/{id}`, `GET .../events` (SSE), `POST .../reply`,
`GET .../agents`, `GET .../log`, `GET .../journal`. Added: `POST .../retry` (continue from the last checkpoint
after status `error`), `GET /readyz`. SSE adds an `activity` event kind (tool-call progress) that the dashboard
ignores, plus `step` / `stage` on every event.

## Known gaps

- ServiceNow, CHG lifecycle and webhooks (G1, intake, evidence) are not built. G2-G5 are answered in the UI.
- The diagram's "unit-test fail -> developer" edge is not wired: the testing agent can only write tests, not run
  them. Failing tests surface later, in the commit agent's validation gate or at deploy.
- Scripted prod smoke tests are not built; G5 is a human confirmation.
- Gate answers are validated by the API *and* by `gate_wait`. If a forged payload ever reached `gate_wait`, the run
  errors and `/retry` may replay the stored bad resume value; the API-side checks make this unreachable in practice.
- A pod killed mid-turn re-runs that turn on retry (at-least-once): tool calls inside it can repeat.
- `requirements.txt` uses ranges. Lock them against Artifactory (`uv lock`) before the first release.
- Model behaviour (tool-calling with always-on thinking, long turns, rate limits at your Anthropic tier) is unverified until a real run. Use a recent `langchain-anthropic` (the 5.5 models are new); check that it round-trips thinking blocks.
- Anthropic API keys are a long-lived secret: store it in the ExternalSecret, never in the repo or image.
- CI assumes repo secrets `ARTIFACTORY_PIP_CONF` and `ARTIFACTORY_NPMRC`, and a prod ECR repo named `sdlc-orbit`;
  confirm both.

## Layout

```
sdlc_orbit/   graph.py (supervisor graph) · agents.py · runtime.py (turn loop) · mcp_tools.py · llm.py · gates.py
              db.py · config.py · state.py · prompts/ · api/ (main, identity, sse, view)
migrations/   application schema (checkpoint tables are created by LangGraph at startup)
toolkits/     salesforce-mcp · confluence-mcp · gitops-mcp (unchanged MCP servers)
frontend/     dashboard source (7-stage model); built into sdlc_orbit/static by the Docker build
tests/        stdlib unittest
```
