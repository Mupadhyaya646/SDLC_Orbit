# gitops-mcp

> **Migration note (SDLC_Orbit).** This server is unchanged by the move from the Cortex-orchestrated
> Felix pipeline to the LangGraph-based SDLC_Orbit. Mentions of Felix / Helix / Cortex below describe the
> previous orchestrator. Kubernetes names such as `felix-dev` and `felix-dev-secrets` are the names currently
> deployed in the infra repo, so they are intentionally left as-is until that repo is renamed. The agents now
> reach this server over streamable HTTP at `/mcp` via `langchain-mcp-adapters` (see `sdlc_orbit/mcp_tools.py`),
> not through a Cortex toolkit registration (the `toolkits/*.json` files are no longer used).


The ONE genuinely new component in the whole Helix Cortex migration — not a port of
anything that exists in the original local tool. Implements the 8 tools
`github-commit-agent.json`'s `toolkits: ["gitops-mcp-toolkit"]` expects:
`git_diff`, `git_classify_changes`, `git_mirror_sfdx_to_metadata`, `git_stage_and_commit`,
`git_push`, `gh_create_pr`, `sf_list_orgs`, `sf_deploy_validate`.

Built following the exact structural pattern of the confirmed-working Jira MCP toolkit
(`Hive-Core/toolkits/jira/`) — FastMCP server, one Python module per tool, a shared
`base.py` for auth/HTTP(subprocess) helpers.

## ⚠️ Security sign-off required before real credentials — read this first

This server is the one component with real new infrastructure risk. The original local
tool ran `git`/`gh` via Claude Code's own Bash tool against **the engineer's own local
checkout**, authenticated with **whatever credentials the engineer personally had**. This
server instead holds **a persistent, server-side clone of the target Salesforce repo**,
authenticated with **a service-account GitHub PAT that has push rights** — a materially
higher-risk credential than "whatever's on someone's laptop." **This component needs its
own security sign-off before it is deployed with real credentials, independent of and in
addition to the rest of the Cortex migration's rollout.** Do not soften this flag or treat
it as already satisfied by any other part of this project's security review.

## Why this server exists at all

A Cortex agent-chain has no Bash tool — only registered MCP toolkit tools. The original
`github-commit` subagent's entire design (6 sequential human-approval gates, explicit
rejection of pre-supplied values, SFDX↔Metadata-API mirroring, target-org validation) is
preserved verbatim in `github-commit-agent.json`'s ported prompt — this server exists
purely to give that prompt real tool calls to make, since it no longer has local Bash.

## Design decision: one persistent clone, not re-clone-per-request

This server maintains **ONE long-lived git clone** on a mounted volume
(`REPO_CLONE_PATH`, default `/data/repo`), kept in sync via `git fetch` + checkout/reset
at the start of every tool call that touches the working tree
(`GitOpsToolBase.ensure_repo_cloned_and_synced` in `app/gitops/base.py`). Re-cloning from
scratch on every single tool call was considered and rejected — too slow (full Salesforce
repos can be large) and wasteful for what is otherwise a stateless-looking MCP server.

**This requires a PersistentVolumeClaim that `deploy-gitops-mcp.yaml` does not currently
have.** Not added by this change (out of scope — a human or a different task should wire
this up once the real target Salesforce repo is known). Required addition:

```yaml
# Add to deploy-gitops-mcp.yaml's Deployment spec.template.spec.containers[0]:
volumeMounts:
  - name: repo-clone
    mountPath: /data/repo
# Add to spec.template.spec:
volumes:
  - name: repo-clone
    persistentVolumeClaim:
      claimName: gitops-mcp-repo-clone
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: gitops-mcp-repo-clone
  namespace: felix-dev
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 5Gi   # adjust to the real target repo's size; Salesforce repos with
                      # years of metadata history can be several GB
```

## Required environment variables

**New to this server** (not currently wired in `deploy-gitops-mcp.yaml`/`external-secrets.yaml`
— only `GITHUB_TOKEN` from the `GITHUB_PAT` secret key and `PORT=6002` are wired today):

| Var | Purpose | Example |
|---|---|---|
| `GITHUB_TOKEN` | Service-account PAT with push rights — **already wired** from `GITHUB_PAT` secret key | (secret) |
| `GITHUB_REPO_URL` | The target Salesforce repo, host+path form (no scheme, no credentials) — **not a fixed/known value anywhere in this project**, operator must set it | `github.com/EliLillyCo/<the-salesforce-repo>` |
| `REPO_CLONE_PATH` | Mount path for the persistent clone | `/data/repo` (Dockerfile default) |
| `GITHUB_PROTECTED_BRANCHES` | Comma-separated branches `git_push` refuses to push to | `main,master` (default if unset) |

**Reused from the sibling `salesforce-mcp` toolkit server** (identical env var names —
both servers authenticate to the same Salesforce org(s), see
`toolkits/salesforce-mcp/app/salesforce/base.py`'s docstring for the full OAuth2
username-password flow this mirrors):

| Var | Purpose |
|---|---|
| `SF_LOGIN_URL` | e.g. `https://login.salesforce.com` or a My Domain URL |
| `SF_USERNAME` | integration user's username |
| `SF_PASSWORD` | integration user's password |
| `SF_SECURITY_TOKEN` | integration user's security token |
| `SF_CLIENT_ID` | connected app consumer key |
| `SF_CLIENT_SECRET` | connected app consumer secret |

`PORT` (default `6002`, matches `deploy-gitops-mcp.yaml`'s `containerPort`) is already wired.

## Operational assumption: multi-org validation needs `sf org login` once per org

`sf_list_orgs`/`sf_deploy_validate` (Gate 5) validate against a **different** org than
whichever one the main pipeline already deployed to (e.g. SIT/UAT, not dev). This
server's own `SF_*` env vars authenticate it to exactly one org non-interactively. For
`sf_deploy_validate` to work against any OTHER org, that org must already be
pre-authenticated in the container's `sf` CLI local auth store — which means an operator
must run `sf org login web -a <alias>` for each additional target org as part of this
server's operational setup/runbook. This is **not automated** by this server (that flow
is inherently interactive/browser-based for orgs the service account doesn't itself own)
— document the real target orgs and run this once per org before Gate 5 can validate
against them.

## How each tool maps to real operations

| Tool | Implementation |
|---|---|
| `git_diff` | Walks `force-app/main/default/<mirrored-type>/` (see `base.py`'s `MIRRORED_TOP_LEVEL_DIRS` — classes, triggers, lwc, aura, flows, layouts, flexipages, permissionsets, profiles, customMetadata, quickActions, queues, applications, standardValueSets), compares each file's content against its `src/`-relative-path counterpart. `objects/**` is never touched. |
| `git_classify_changes` | Pure comparison — accepts the AI-authored path list as a **parameter** from the calling agent (this server has no database connection to the separate `helix-cortex-backend` Postgres instance where that data actually lives) and splits `git_diff`'s output against it. |
| `git_mirror_sfdx_to_metadata` | Copies (or deletes, for removed files) each approved path from `force-app/main/default/` to `src/` — same relative-path mapping as `git_diff`. |
| `git_stage_and_commit` | `git add --` with the **explicit** path list (hard-rejects `.`/`-A`/`--all`/`*`), then `git commit -m`. |
| `git_push` | Refuses on a protected branch (`GITHUB_PROTECTED_BRANCHES`); otherwise `git push origin <branch>`, credential injected via the remote URL set during repo sync, never as a bare CLI arg. |
| `gh_create_pr` | `gh pr create --title ... --body ... --base ... --head ... --reviewer ...`, authenticated via `GH_TOKEN` (set from this server's `GITHUB_TOKEN` for that one subprocess call only). |
| `sf_list_orgs` | Authenticates this server's own `SF_*` env-var org via OAuth2, AND (if the `sf` CLI has other pre-authenticated orgs) merges in `sf org list --all --json`'s results — de-duplicated by username. |
| `sf_deploy_validate` | Shells out to `sf project deploy validate --source-dir src --target-org <alias> ...` against the persistent clone's already-committed `src/` tree — same documented rationale as the sibling salesforce-mcp toolkit's own `sf_deploy_validate` (CLI, not hand-rolled Metadata API SOAP) for authenticating a non-owned target org via `sf org login access-token`, only when `target_org` matches this server's own `SF_USERNAME`. |

## What this toolkit does NOT cover

- Only the metadata types in `MIRRORED_TOP_LEVEL_DIRS` are mirrored — not every Salesforce
  metadata type. `objects/**` is unconditionally excluded (SFDX decomposes custom objects
  into per-object folders; Metadata API uses one file per object; that conversion needs
  `sf project convert`, which this toolkit does not attempt — same as the original design's
  Critical Rule #1).
- `sf_deploy_validate`'s target-org authentication for non-owned orgs is a manual,
  one-time-per-org operational step (`sf org login web`), not automated.
- No automated credential rotation — if `GITHUB_TOKEN` is rotated in Secrets Manager, the
  running pod's env var won't update until it restarts (standard k8s `ExternalSecret`
  behavior; not specific to this server).

## Verification performed in this environment

All 14 `.py` files pass `python3 -m py_compile`. **Not functionally run** — this sandbox
has no Docker daemon and no outbound network to install `mcp`/`fastapi`/`requests`, and
no `git`/`gh`/`sf` CLIs to exercise. A real build and smoke test must happen in Lilly's own
CI/CATS environment before trusting this server with real credentials.
