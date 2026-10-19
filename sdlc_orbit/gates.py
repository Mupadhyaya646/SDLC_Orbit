"""Pure helpers for gate detection and for parsing specialist-agent output.

No third-party imports on purpose: everything here is deterministic string
logic, so it is unit-testable without LangGraph, an LLM, or a database.

Ported from the Cortex-era ``app/pipeline.py`` (``looks_like_gate``,
``_extract_prompt_block``, ``_parse_code_review_verdict``,
``_build_docs_prompt``) with two deliberate hardenings, both documented
inline:

* ``parse_code_review_verdict`` prefers the agent's own ``Verdict:`` line and
  no longer treats an unrelated mention of "approved" in prose as a verdict.
* ``choice`` / ``parse_design_reply`` normalise punctuation so "[F]", "F.",
  and "f" all read as the same answer.

Every ambiguous case fails *closed*: an unrecognised code-review verdict is
treated like CHANGES REQUIRED, never like an approval.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Gate detection
# ---------------------------------------------------------------------------

# An agent "ends its turn at a gate" when its final message (no tool call)
# contains a bracketed option such as [Y], [A], [F], [1], or the design agent's
# "(yes / no / changes)" prompt. Identical to the Cortex-era heuristic so
# behaviour is unchanged for the unmodified agent prompts.
_BRACKET_OPTION = re.compile(r"\[[A-Za-z0-9]{1,3}\]\s*[^\n\[]{0,70}")
_YES_NO_CHANGES = re.compile(r"\(\s*yes\s*/\s*no\s*/\s*changes\s*\)", re.IGNORECASE)


def looks_like_gate(text: str) -> bool:
    """True when ``text`` reads like a question that needs a human answer."""
    if not text:
        return False
    if _BRACKET_OPTION.search(text):
        return True
    return bool(_YES_NO_CHANGES.search(text))


def has_yes_no_changes(text: str) -> bool:
    """True when the text itself already carries the design-confirmation prompt."""
    return bool(_YES_NO_CHANGES.search(text or ""))


def ends_with_question(text: str) -> bool:
    """A genuine clarifying question: a '?' within the final ~300 characters.

    The design prompt allows exactly one case where it may skip the plan: a
    missing detail it must ask the human about. Without this check the pipeline
    would force a plan out of it and override that legitimate question.
    """
    return "?" in (text or "").strip()[-300:]


# ---------------------------------------------------------------------------
# Human-answer normalisation
# ---------------------------------------------------------------------------


def choice(text: str | None) -> str:
    """First alphanumeric character of a human reply, lower-cased.

    "[F] fix", "F.", " f " -> "f".  Empty / non-alphanumeric -> "".
    """
    for ch in (text or "").strip().lower():
        if ch.isalnum():
            return ch
    return ""


def parse_design_reply(text: str | None) -> str:
    """Map the reply to the design-confirmation gate to yes / no / changes.

    Same rules as the Cortex-era pipeline: a bare "no" (or "no ...") aborts,
    "yes"/"y" proceeds, anything else is treated as change instructions.
    """
    answer = (text or "").strip().lower().rstrip(".!")
    if answer == "no" or answer.startswith("no ") or answer == "n":
        return "no"
    if answer in ("yes", "y"):
        return "yes"
    return "changes"


# ---------------------------------------------------------------------------
# Design-agent plan parsing
# ---------------------------------------------------------------------------


def extract_prompt_block(text: str, label: str) -> str | None:
    """Return the triple-quoted body after ``<LABEL> PROMPT:``.

    ``None`` when the block is absent or explicitly empty / "none" / "n/a" --
    i.e. that specialist has no work this round.
    """
    m = re.search(
        rf"{re.escape(label)}\s+PROMPT:\s*\"\"\"(.*?)\"\"\"",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    block = m.group(1).strip()
    if not block or block.lower() in ("none", "n/a"):
        return None
    return block


def parse_design_plan(text: str) -> tuple[str | None, str | None]:
    """(admin_prompt, dev_prompt) extracted from a design-agent message."""
    return extract_prompt_block(text, "ADMIN"), extract_prompt_block(text, "DEV")


# ---------------------------------------------------------------------------
# Code-review verdict
# ---------------------------------------------------------------------------

VERDICT_APPROVED = "approved"
VERDICT_WARNINGS = "approved_with_warnings"
VERDICT_CHANGES = "changes_required"
VERDICT_UNKNOWN = "unknown"

_VERDICT_LINE = re.compile(r"^[#\s>*_`]*verdict\s*[:\-\u2013\u2014]\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _classify_verdict(fragment: str) -> set[str]:
    hits: set[str] = set()
    if re.search(r"CHANGES\s+REQUIRED", fragment, re.IGNORECASE):
        hits.add(VERDICT_CHANGES)
    if re.search(r"APPROVED\s+WITH\s+WARNINGS?", fragment, re.IGNORECASE):
        hits.add(VERDICT_WARNINGS)
    if re.search(r"\bAPPROVED\b(?!\s+WITH\s+WARNING)", fragment, re.IGNORECASE):
        hits.add(VERDICT_APPROVED)
    return hits


def parse_code_review_verdict(text: str) -> str:
    """One of the agent's three documented verdicts, or ``unknown``.

    Resolution order:
    1. A ``Verdict: ...`` line naming exactly one verdict (an echoed legend
       such as "APPROVED / APPROVED WITH WARNINGS / CHANGES REQUIRED" names
       several and is skipped).
    2. Only if the text contains the word "verdict" at all: the whole-text
       fallback, where CHANGES REQUIRED beats WARNINGS beats APPROVED.
    3. Otherwise ``unknown`` -- e.g. the agent's observed "NOT APPLICABLE --
       NOTHING TO REVIEW" improvisation. Callers must treat ``unknown`` like
       CHANGES REQUIRED; never as an approval.
    """
    text = text or ""
    for m in _VERDICT_LINE.finditer(text):
        hits = _classify_verdict(m.group(1))
        if len(hits) == 1:
            return next(iter(hits))
    if not re.search(r"verdict", text, re.IGNORECASE):
        return VERDICT_UNKNOWN
    hits = _classify_verdict(text)
    for verdict in (VERDICT_CHANGES, VERDICT_WARNINGS, VERDICT_APPROVED):
        if verdict in hits:
            return verdict
    return VERDICT_UNKNOWN


def verdict_passes(verdict: str) -> bool:
    """True only for an explicit approval (with or without warnings)."""
    return verdict in (VERDICT_APPROVED, VERDICT_WARNINGS)


VERDICT_LABELS = {
    VERDICT_APPROVED: "approved",
    VERDICT_WARNINGS: "approved with warnings",
    VERDICT_CHANGES: "changes required (skipped past, proceeded with warning)",
    VERDICT_UNKNOWN: "verdict not recognised (skipped past, proceeded with warning)",
}


# ---------------------------------------------------------------------------
# Commit / deploy outcome (best-effort; "unknown" never blocks the pipeline)
# ---------------------------------------------------------------------------

_COMMIT_STATUS = re.compile(
    r"^#{1,6}\s*Commit\s*\n\s*Status:\s*(SUCCESS|FAILED|CANCELLED)\b(?!\s*/)",
    re.IGNORECASE | re.MULTILINE,
)


def parse_commit_status(text: str) -> str:
    """'success' | 'failed' | 'cancelled' | 'unknown' from the commit agent's memory block."""
    m = _COMMIT_STATUS.search(text or "")
    return m.group(1).lower() if m else "unknown"


_DEPLOY_STATUS = re.compile(r"Status:\s*[^\w\n]*\s*(SUCCESS|FAILED)\b(?!\s*/)", re.IGNORECASE)
_DEPLOY_BLOCKED = re.compile(r"DEPLOYMENT\s+BLOCKED", re.IGNORECASE)
_DEPLOY_CANCELLED = re.compile(r"\b(?:deployment|deploy)\b[^.\n]{0,40}\bcancel+ed\b", re.IGNORECASE)


def parse_deploy_status(text: str) -> str:
    """'success' | 'failed' | 'blocked' | 'cancelled' | 'unknown' from the devops agent's report.

    An explicit ``Status:`` line wins; otherwise BLOCKED, then CANCELLED.
    Anything else is 'unknown', which the pipeline treats as 'continue to the
    human QA gate' (a person verifies the deploy there).
    """
    text = text or ""
    m = _DEPLOY_STATUS.search(text)
    if m:
        return m.group(1).lower()
    if _DEPLOY_BLOCKED.search(text):
        return "blocked"
    if _DEPLOY_CANCELLED.search(text):
        return "cancelled"
    return "unknown"


# ---------------------------------------------------------------------------
# Documentation pre-flight
# ---------------------------------------------------------------------------


def build_docs_prompt(ctx: dict[str, Any]) -> str:
    """Invocation text for the documentation agent from pre-flight answers."""
    lines = ["Build the LSC Design Document for the work completed in this session."]
    destination = ctx.get("docs_destination")
    if destination == "l":
        lines.append(f"Destination: Local file. Format: {ctx.get('docs_local_format') or 'markdown'}.")
    elif destination == "c":
        location = ctx.get("docs_confluence_location", "")
        if ctx.get("docs_confluence_new"):
            lines.append(f"Destination: Confluence, new page. Location/module: {location}.")
        else:
            lines.append(f"Destination: Confluence, update existing page at: {location}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prod pre-flight guard (deterministic; no LLM)
# ---------------------------------------------------------------------------

# Gates that must have been answered by a real human before anything may touch
# Prod. Names match the gate_name values written by graph.py.
REQUIRED_PROD_GATES = ("qa_confirm", "uat_approval", "pr_approval", "merge_confirm")


def prod_preflight_problems(gates: list[dict[str, Any]], *, uat_valid: bool) -> list[str]:
    """Reasons Prod must NOT be touched yet; empty list means clear to go.

    ``gates`` is the session's gate_log rows (dicts with ``gate_name``,
    ``answer``, ``answered_by``).  A required gate counts only if its most
    recent row has a non-empty answer and an ``answered_by`` identity.
    """
    problems: list[str] = []
    latest: dict[str, dict[str, Any]] = {}
    for g in gates:
        latest[g.get("gate_name", "")] = g
    for name in REQUIRED_PROD_GATES:
        row = latest.get(name)
        if row is None:
            problems.append(f"gate '{name}' was never raised")
        elif not (row.get("answer") or "").strip():
            problems.append(f"gate '{name}' is still open")
        elif not (row.get("answered_by") or "").strip():
            problems.append(f"gate '{name}' has no recorded human identity")
    if not uat_valid:
        problems.append("code changed after UAT approval; QA deploy and UAT must be repeated")
    return problems
