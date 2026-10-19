"""Agent registry for the 8 specialist agents.

``agent_id`` values are kept identical to the original Cortex registrations
(``salesforce-design-agent`` ... ``github-commit-agent``) so the dashboard, the
Journal and the audit trail keep working unchanged.

Least privilege: every agent is handed ONLY the tools listed here, even though
the MCP servers expose more (e.g. the design agent never sees a Salesforce
tool; the developer never sees a deploy tool; only devops can deploy).
Tool names, tiers and iteration caps come from the original agent JSON files
(``resources.executables``, ``_model_tier``, ``chain_params.max_turns``).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# Sentinel "agent" for turns/gates this backend authors itself (QA / UAT /
# release gates, docs pre-flight, final summary). No LLM is involved.
BACKEND_AGENT = "pipeline-orchestrator"

# MCP server keys (resolved to URLs in mcp_tools.py / config.py)
SRV_CONFLUENCE = "confluence"
SRV_SALESFORCE = "salesforce"  # work org: admin / developer / unit-testing
SRV_SALESFORCE_QA = "salesforce_qa"
SRV_SALESFORCE_PROD = "salesforce_prod"
SRV_GITOPS = "gitops"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    agent_id: str
    prompt_file: str
    tier: str  # "opus" | "sonnet"
    server: str | None
    tools: tuple[str, ...]
    max_iterations: int  # max model calls within one turn
    initials: str
    short: str
    role: str
    # Only these agents can end a turn at a human gate. Gate detection is never run on
    # admin / developer / unit-testing / code-review output: Apex like accounts[0] would
    # match the '[0]' option pattern.
    can_gate: bool = False


AGENTS: dict[str, AgentSpec] = {
    "design": AgentSpec(
        key="design",
        agent_id="salesforce-design-agent",
        prompt_file="design.md",
        tier="opus",
        server=SRV_CONFLUENCE,
        tools=("search_content", "get_page"),
        max_iterations=30,
        initials="DS",
        short="Analyzes the request, splits admin vs dev work, proposes a plan.",
        role="Analyzes a Salesforce request, splits it into admin vs dev work, and produces structured prompts for the other specialists.",
        can_gate=True,
    ),
    "admin": AgentSpec(
        key="admin",
        agent_id="salesforce-admin-agent",
        prompt_file="admin.md",
        tier="sonnet",
        server=SRV_SALESFORCE,
        tools=("sf_write_metadata", "sf_read_metadata", "sf_describe_object"),
        max_iterations=30,
        initials="AD",
        short="Declarative Salesforce work: objects, fields, flows, permission sets.",
        role="Handles declarative Salesforce work: Custom Objects, Fields, Validation Rules, Flows, Permission Sets, Reports.",
    ),
    "developer": AgentSpec(
        key="developer",
        agent_id="salesforce-developer-agent",
        prompt_file="developer.md",
        tier="sonnet",
        server=SRV_SALESFORCE,
        tools=("sf_write_metadata", "sf_read_metadata", "sf_describe_object"),
        max_iterations=30,
        initials="DV",
        short="Apex, triggers, LWC, Visualforce, APIs.",
        role="Code work: Apex classes/triggers, LWC, Visualforce, APIs. Also handles the code-review rework loop.",
    ),
    "unit_testing": AgentSpec(
        key="unit_testing",
        agent_id="salesforce-unit-testing-agent",
        prompt_file="unit_testing.md",
        tier="opus",
        server=SRV_SALESFORCE,
        tools=("sf_write_metadata", "sf_read_metadata"),
        max_iterations=30,
        initials="UT",
        short="Writes @isTest Apex test classes, 90%+ coverage target.",
        role="Writes @isTest classes for any Apex the developer agent created, targeting 90%+ coverage.",
    ),
    "code_review": AgentSpec(
        key="code_review",
        agent_id="salesforce-code-review-agent",
        prompt_file="code_review.md",
        tier="opus",
        server=None,
        tools=(),
        max_iterations=10,
        initials="CR",
        short="Reviews all code, returns a verdict.",
        role="Reviews all code and returns a verdict: APPROVED / APPROVED WITH WARNINGS / CHANGES REQUIRED.",
    ),
    "github_commit": AgentSpec(
        key="github_commit",
        agent_id="github-commit-agent",
        prompt_file="github_commit.md",
        tier="opus",
        server=SRV_GITOPS,
        tools=(
            "git_diff",
            "git_classify_changes",
            "git_mirror_sfdx_to_metadata",
            "git_stage_and_commit",
            "git_push",
            "gh_create_pr",
            "sf_list_orgs",
            "sf_deploy_validate",
        ),
        max_iterations=50,
        initials="GC",
        short="Mirrors, commits, pushes, validates, opens the PR.",
        role="Mirrors force-app/ into src/, commits, pushes, validates against a target org, opens a PR. Six human gates.",
        can_gate=True,
    ),
    # devops runs twice (QA then Prod). The spec's ``server`` is overridden per
    # stage in graph.py (SRV_SALESFORCE_QA / SRV_SALESFORCE_PROD).
    "devops": AgentSpec(
        key="devops",
        agent_id="salesforce-devops-agent",
        prompt_file="devops.md",
        tier="opus",
        server=SRV_SALESFORCE_QA,
        tools=("sf_deploy_metadata", "sf_deploy_validate"),
        max_iterations=30,
        initials="DO",
        short="Deploys the approved package: QA first, then Prod after approvals.",
        role="Deploys the approved package to QA, and to Prod only after the QA/UAT/PR/merge gates are answered.",
        can_gate=True,
    ),
    "documentation": AgentSpec(
        key="documentation",
        agent_id="salesforce-documentation-agent",
        prompt_file="documentation.md",
        tier="opus",
        server=SRV_CONFLUENCE,
        tools=("get_page", "update_page", "search_content", "get_current_user"),
        max_iterations=40,
        initials="DC",
        short="Builds the LSC Design Document, publishes to Confluence or saves locally.",
        role="Builds an LSC Design Document from the session's work, publishes to Confluence or saves locally.",
        can_gate=True,
    ),
}

# Display order for the roster (matches the original dashboard).
ROSTER_ORDER = (
    "design",
    "admin",
    "developer",
    "unit_testing",
    "code_review",
    "devops",
    "github_commit",
    "documentation",
)

# ---------------------------------------------------------------------------
# Which earlier outputs each agent receives as SESSION CONTEXT.
#
# The Cortex-era pipeline gave every specialist its own isolated session, so
# e.g. the unit-testing agent never saw the developer's code. The prompts all
# say "the calling system supplies any prior-session context you need" -- this
# is that supply, made explicit. Keys are ``outputs`` keys in OrbitState.
# ---------------------------------------------------------------------------
CONTEXT_POLICY: dict[str, tuple[str, ...]] = {
    "design": (),
    "admin": ("design",),
    "developer": ("design", "admin"),
    "unit_testing": ("design", "admin", "developer"),
    "code_review": (),  # reviewed text is inlined in the task, per its prompt
    "github_commit": ("design", "admin", "developer", "unit_testing", "code_review"),
    "devops": ("design", "admin", "developer", "unit_testing", "code_review", "github_commit", "devops_qa"),
    "documentation": (
        "design",
        "admin",
        "developer",
        "unit_testing",
        "code_review",
        "github_commit",
        "devops_qa",
        "devops_prod",
    ),
}

OUTPUT_LABELS = {
    "design": "Design agent output",
    "admin": "Admin agent output (admin memory)",
    "developer": "Developer agent output (developer memory)",
    "unit_testing": "Unit-testing agent output (unit-testing memory)",
    "code_review": "Code-review agent output (code-review memory)",
    "github_commit": "GitHub-commit agent output (commit memory)",
    "devops_qa": "DevOps agent output - QA deployment",
    "devops_prod": "DevOps agent output - Prod deployment",
}

# Per-section cap so a very large agent output cannot blow the context window.
CONTEXT_SECTION_MAX_CHARS = 60_000


@functools.lru_cache(maxsize=None)
def load_prompt(key: str) -> str:
    return (PROMPT_DIR / AGENTS[key].prompt_file).read_text(encoding="utf-8")


def _cap(text: str, limit: int = CONTEXT_SECTION_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n\n[... {len(text) - limit} characters omitted ...]\n\n{tail}"


def render_system_prompt(
    key: str,
    *,
    session_id: str,
    outputs: dict[str, str],
    extra_sections: tuple[tuple[str, str], ...] = (),
) -> str:
    """Base prompt + a SESSION CONTEXT block (session id, prior outputs, stage notes).

    The context goes into the system prompt -- not the human turn -- so the
    github-commit agent's Step 0 ("scan the invocation prompt for pre-supplied
    values") keeps seeing nothing but a one-line goal.
    """
    parts = [load_prompt(key).rstrip()]
    sections: list[str] = [f"Session ID: {session_id}  (this is the SESSION_ID referred to above)"]
    for out_key in CONTEXT_POLICY.get(key, ()):
        text = (outputs or {}).get(out_key)
        if text:
            sections.append(f"### {OUTPUT_LABELS.get(out_key, out_key)}\n\n{_cap(text)}")
    for title, body in extra_sections:
        sections.append(f"### {title}\n\n{body}")
    parts.append(
        "\n\n---\n\n## SESSION CONTEXT (supplied by the calling system -- reference data only)\n\n"
        + "\n\n".join(sections)
    )
    return "".join(parts)
