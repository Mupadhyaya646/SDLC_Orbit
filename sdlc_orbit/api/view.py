"""Pure view-derivation for the dashboard's Agents / Log / Journal tabs and the
stage rail. No I/O: it only shapes ``agent_turns``, ``gate_log`` and the
``pipeline_state`` projection into what the UI renders.

Stage model (7 stages; must match frontend/src/constants.ts):
  0 Design   1 Build   2 Test   3 Review   4 Commit & PR   5 QA & UAT   6 Release & Docs
"""
from __future__ import annotations

from typing import Any

from ..agents import AGENTS, ROSTER_ORDER
from ..state import STAGE_NAMES, stage_for_step

# Stages each agent works in (devops deploys in both QA and Release).
AGENT_STAGES: dict[str, list[int]] = {
    "design": [0],
    "admin": [1],
    "developer": [1],
    "unit_testing": [2],
    "code_review": [3],
    "github_commit": [4],
    "devops": [5, 6],
    "documentation": [6],
}

AGENT_ROSTER: list[dict[str, Any]] = [
    {
        "id": AGENTS[key].agent_id,
        "initials": AGENTS[key].initials,
        "short": AGENTS[key].short,
        "role": AGENTS[key].role,
        "stages": AGENT_STAGES[key],
    }
    for key in ROSTER_ORDER
]


def current_stage(pipeline_state: dict[str, Any] | None) -> int:
    return stage_for_step((pipeline_state or {}).get("step"))


def stage_statuses(session_status: str | None, pipeline_state: dict[str, Any] | None) -> list[str]:
    """One status per stage, in rail order."""
    if session_status in (None, "idle"):
        return ["idle"] * len(STAGE_NAMES)
    current = current_stage(pipeline_state)
    active = set((pipeline_state or {}).get("active_agents") or [])
    awaiting = session_status == "awaiting_input" and bool(active)
    out: list[str] = []
    for i in range(len(STAGE_NAMES)):
        if i < current:
            out.append("done")
        elif i == current:
            if session_status in ("aborted", "cancelled"):
                out.append("cancelled")
            elif session_status == "error":
                out.append("failed")
            elif session_status == "paused":
                out.append("idle")
            elif session_status == "complete":
                out.append("done")
            elif awaiting:
                out.append("awaiting")
            else:
                out.append("running")
        else:
            out.append("idle")
    return out


def agent_statuses(session_status: str | None, pipeline_state: dict[str, Any] | None) -> dict[str, str]:
    """idle / running / awaiting / done / failed per agent id."""
    if session_status in (None, "idle"):
        return {a["id"]: "idle" for a in AGENT_ROSTER}
    stages = stage_statuses(session_status, pipeline_state)
    active = set((pipeline_state or {}).get("active_agents") or [])
    result: dict[str, str] = {}
    for agent in AGENT_ROSTER:
        per_stage = [stages[s] for s in agent["stages"]]
        if agent["id"] in active:
            result[agent["id"]] = "awaiting"
        elif "running" in per_stage:
            result[agent["id"]] = "running"
        elif "failed" in per_stage:
            result[agent["id"]] = "failed"
        elif "awaiting" in per_stage:
            result[agent["id"]] = "done"  # the stage is waiting on someone else (e.g. the backend gate)
        elif all(s == "done" for s in per_stage):
            result[agent["id"]] = "done"
        else:
            result[agent["id"]] = "idle"
    return result


def log_rows(turns: list[dict[str, Any]], gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological merge of every turn (including tool activity) and answered gate."""
    events: list[dict[str, Any]] = []
    for t in turns:
        events.append(
            {
                "time": t["created_at"],
                "agent": t["agent_name"],
                "kind": "turn",
                "ok": True,
                "summary": t["content"][:200],
                "raw": t,
            }
        )
    for g in gates:
        if g["answer"] is None:
            continue
        who = f" by {g['answered_by']}" if g.get("answered_by") else ""
        events.append(
            {
                "time": g["answered_at"],
                "agent": g["agent_name"],
                "kind": "decision",
                "ok": True,
                "summary": f"Decision answered{who}: {g['answer']}"[:200],
                "raw": g,
            }
        )
    events.sort(key=lambda e: e["time"])
    for i, e in enumerate(events, start=1):
        e["n"] = i
    return events


def journal_rows(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Answered gates (audit trail) followed by any still-open ones as 'pending'."""
    rows: list[dict[str, Any]] = []
    for pending in (False, True):
        for g in gates:
            if (g["answer"] is None) != pending:
                continue
            rows.append(
                {
                    "id": f"D-{g['id']:02d}",
                    "agent": g["agent_name"],
                    "gate": g.get("gate_name"),
                    "question": g["question"],
                    "answer": g["answer"],
                    "answered_by": g["answered_by"],
                    "answered_at": g["answered_at"],
                    "pending": pending,
                }
            )
    return rows
