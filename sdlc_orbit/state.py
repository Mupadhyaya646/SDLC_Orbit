"""Graph state and the step -> dashboard-stage mapping."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_dict(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer: per-key replace. A node returns only the keys it changed."""
    return {**(left or {}), **(right or {})}


class OrbitState(TypedDict, total=False):
    # identity -------------------------------------------------------------
    session_id: str
    request: str

    # per-agent conversation threads (the equivalent of one Cortex session per
    # agent) and each agent's latest final output (the "memory" later agents get)
    threads: Annotated[dict[str, list[Any]], merge_dict]
    outputs: Annotated[dict[str, str], merge_dict]

    # human gate plumbing -------------------------------------------------
    gate: dict[str, Any] | None  # open gate: gate_id, agent, name, question, step
    gate_answer: dict[str, Any] | None  # text, answered_by, gate_name (set by gate_wait)
    resume_node: str | None  # node that opened the gate and consumes its answer

    # design --------------------------------------------------------------
    design_message: str
    design_done: bool
    design_auto_retried: bool
    admin_prompt: str | None
    dev_prompt: str | None
    has_admin: bool
    has_dev: bool
    admin_done: bool
    dev_done: bool
    testing_done: bool

    # review / rework -----------------------------------------------------
    code_review_verdict: str
    review_warning: bool
    rework_count: int  # automatic review-driven loops (capped)
    human_rework_count: int  # human-requested loops (QA / UAT / PR / hotfix; uncapped)
    rework_target: str | None  # "developer" | "admin" while a rework is pending
    rework_text: str | None

    # commit / deploy -----------------------------------------------------
    commit_run: int
    qa_run: int
    prod_run: int
    uat_valid: bool

    # docs pre-flight -----------------------------------------------------
    docs_substep: str | None
    docs_destination: str | None
    docs_local_format: str | None
    docs_confluence_new: bool
    docs_confluence_location: str | None
    skip_docs: bool

    # terminal ------------------------------------------------------------
    final_status: str | None  # "aborted" | None (finish node sets 'complete')
    final_note: str | None


# ---------------------------------------------------------------------------
# Steps (what the dashboard's stage rail reads) -> 7 stages
# ---------------------------------------------------------------------------

STAGE_NAMES = ["Design", "Build", "Test", "Review", "Commit & PR", "QA & UAT", "Release & Docs"]

STAGE_DESCRIPTIONS = [
    "Analyzes the request, splits it into admin vs dev work, and proposes a plan for your approval.",
    "Implements declarative admin work and Apex/LWC dev work.",
    "Writes @isTest Apex test classes targeting 90%+ coverage.",
    "Reviews all code and returns a verdict; rejections loop back to the developer (capped).",
    "Mirrors changes, commits, pushes, validates against a target org and opens the PR - six human gates.",
    "Deploys to QA, then waits for the SME's confirmation and UAT approval.",
    "PR approval and merge, Prod deploy, Prod confirmation, then the design document.",
]

STEP_TO_STAGE: dict[str, int] = {
    "design": 0,
    "build": 1,
    "test": 2,
    "review": 3,
    "commit": 4,
    "qa_deploy": 5,
    "qa_confirm": 5,
    "uat": 5,
    "pr_approval": 6,
    "merge": 6,
    "prod_preflight": 6,
    "prod_deploy": 6,
    "prod_confirm": 6,
    "docs_preflight": 6,
    "docs": 6,
    "complete": 6,
}


def stage_for_step(step: str | None) -> int:
    return STEP_TO_STAGE.get(step or "", 0)
