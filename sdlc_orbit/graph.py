"""sdlc_orbit_graph -- the supervisor StateGraph (Lane 3 of the architecture).

Design rules (from the architecture diagram):

* Routing is deterministic Python. The graph delegates to the specialist agents
  and never implements anything itself; no LLM decides what runs next.
* A human gate is a separate, pure node (``gate_wait``) that only calls
  ``interrupt()``. LangGraph re-runs an interrupted node from its start on
  resume, so keeping the gate node free of LLM calls and tool calls means
  nothing is ever executed twice. Agent nodes finish their turn, record the
  gate, and route to ``gate_wait``; the answer routes back to the node that
  opened the gate.
* Gate answers are accepted only as a payload stamped by the API/webhook layer
  (verified identity, matching gate id). Agent output can never answer a gate.
* Agents get the tools on their allow-list and nothing else.

Flow (ServiceNow / CHG lifecycle intentionally not implemented):

    design -> [design_confirm gate] -> admin -> developer -> unit_testing
           -> code_review -(auto rework x N, then G6 escalation)-> github_commit
           -> qa_deploy -> qa_confirm(G2) -> uat_approval(G3)
           -> pr_approval(G4) -> merge_confirm -> prod_preflight
           -> prod_deploy -> prod_confirm(G5, G6 on failure)
           -> docs_preflight -> documentation -> finish

Any human-requested "fix" (QA / UAT / PR / hotfix) loops back through
developer -> unit_testing -> code_review -> github_commit -> qa_deploy -> G2 -> G3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents import AGENTS, BACKEND_AGENT, SRV_SALESFORCE_PROD, SRV_SALESFORCE_QA, render_system_prompt
from .gates import (
    VERDICT_LABELS,
    build_docs_prompt,
    choice,
    ends_with_question,
    has_yes_no_changes,
    looks_like_gate,
    parse_code_review_verdict,
    parse_commit_status,
    parse_deploy_status,
    parse_design_plan,
    parse_design_reply,
    prod_preflight_problems,
    verdict_passes,
)
from .mcp_tools import McpUnavailable
from .runtime import AgentIterationLimit, run_turn
from .state import OrbitState, stage_for_step

logger = logging.getLogger("sdlc_orbit.graph")

# Keys mirrored into pipeline_state.context for the dashboard.
_UI_CONTEXT_KEYS = (
    "has_admin",
    "admin_done",
    "has_dev",
    "dev_done",
    "testing_done",
    "code_review_verdict",
    "rework_count",
    "human_rework_count",
    "uat_valid",
    "skip_docs",
)

_DESIGN_NUDGE = (
    "Your previous response did not include an ADMIN PROMPT or DEV PROMPT block. You are a PLANNER -- "
    "you always have the Salesforce domain knowledge to produce a plan directly from the request text, "
    "even without a Confluence match and even though you have no Salesforce tools yourself. Produce the "
    "full design plan now, ending with real \U0001F4DD ADMIN PROMPT: and \U0001F4DD DEV PROMPT: blocks "
    "using the exact Output Format from your instructions -- do not explain why you can't do Salesforce "
    "work; you were never asked to."
)

_COMMIT_GOAL = "Commit and push the work completed in this session."  # one line, per the orchestrator's hard rules
_UNIT_TEST_TASK = "Write @isTest Apex test classes (90%+ coverage target) for the Apex code just created in this session."
_UNIT_TEST_REWORK_SUFFIX = (
    "\n\nThe developer has since revised the code to address review or approval feedback; "
    "update or extend the test classes to match the revised code."
)

Q_DESIGN_CONFIRM = "Proceed with this plan? (yes / no / changes)"
Q_QA_CONFIRM = (
    "QA deployment finished. Please have the business SME confirm the change is complete and correct in QA (G2).\n"
    "[Y] Confirmed complete\n[F] Fix needed (send back to the developer)\n[C] Cancel the pipeline\nYour choice:"
)
Q_UAT = (
    "UAT approval (G3). Has the business user approved the change in UAT?\n"
    "[Y] Approved\n[R] Rejected (send back to the developer)\n[C] Cancel the pipeline\nYour choice:"
)
Q_PR = (
    "PR approval (G4). Has the tech lead approved the pull request?\n"
    "[Y] Approved\n[R] Changes requested (send back to the developer)\n[C] Cancel the pipeline\nYour choice:"
)
Q_MERGE = (
    "Merge the approved PR into the release branch. Merging is a human or branch-protection action; "
    "no agent merges.\n[M] Merged\n[C] Cancel the pipeline\nYour choice:"
)
Q_PROD_CONFIRM = (
    "Production deployment finished. Please smoke-test Prod and have the business SME confirm (G5).\n"
    "[Y] Correct\n[N] Incorrect\nYour choice:"
)
Q_PROD_ESCALATION = (
    "Prod was reported incorrect (G6). No agent will touch Prod again on its own; a human decides.\n"
    "[H] Hotfix (send back to the developer; the whole QA / UAT / PR chain repeats)\n"
    "[R] Rolled back manually (end the session)\n[C] Cancel the pipeline\nYour choice:"
)
Q_DOCS_Q1 = "Documentation pre-flight.\n[C] Confluence\n[L] Local\n[S] Skip\nYour choice:"
Q_DOCS_LOCAL = "What format should the local doc be saved as? (e.g. markdown, docx):"
Q_DOCS_NEW_OR_EXISTING = "Confluence: new page or update existing? ([N] New / [E] Existing):"
Q_DOCS_LOCATION = "Confluence space/page location (or module name for the new page):"

_OPTIONS_HINT = "Please answer with one of the listed options.\n\n"


@dataclass
class Deps:
    """Everything the graph needs from the outside world (injectable for tests)."""

    llm: Callable[[str], Any]  # tier -> chat model
    tools: Callable[[str | None, tuple[str, ...]], Awaitable[list[Any]]]  # (server, allow-list) -> tools
    store: Any  # append_turn, record_gate, set_ui_state, set_status, list_gates, get_session, record_handoff
    max_rework_loops: int = 3
    require_design_confirmation: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def build_graph(deps: Deps) -> StateGraph:
    """Return the *uncompiled* graph; the caller compiles it with a checkpointer."""

    # ------------------------------------------------------------------ helpers

    async def say(state: dict, agent_id: str, text: str, step: str, role: str = "assistant") -> None:
        await deps.store.append_turn(state["session_id"], agent_id, role, text, step, stage_for_step(step))

    async def publish(state: dict, step: str, *, agent: str | None, status: str) -> None:
        ui = {
            "step": step,
            "active_agents": [agent] if (status == "awaiting_input" and agent) else [],
            "context": {k: state.get(k) for k in _UI_CONTEXT_KEYS if state.get(k) is not None},
        }
        await deps.store.set_ui_state(state["session_id"], ui)
        await deps.store.set_status(state["session_id"], status, current_agent=agent)

    async def open_gate(
        state: dict,
        upd: dict,
        *,
        agent: str,
        name: str,
        question: str,
        step: str,
        resume_node: str,
        emit_turn: bool,
    ) -> None:
        """Record a gate and arrange for the graph to route to ``gate_wait``."""
        if emit_turn:
            await say(state, agent, question, step)
        gate_id = await deps.store.record_gate(state["session_id"], agent, name, question)
        upd["gate"] = {"gate_id": gate_id, "agent": agent, "name": name, "question": question, "step": step}
        upd["resume_node"] = resume_node
        upd["gate_answer"] = None
        await publish({**state, **upd}, step, agent=agent, status="awaiting_input")

    def answer_for(state: dict, node: str) -> dict | None:
        if state.get("resume_node") == node and state.get("gate_answer"):
            return state["gate_answer"]
        return None

    def consume(upd: dict) -> None:
        upd["gate_answer"] = None
        upd["resume_node"] = None

    def abort(upd: dict, note: str) -> None:
        upd["final_status"] = "aborted"
        upd["final_note"] = note

    def start_rework(state: dict, upd: dict, reason: str, *, auto: bool) -> None:
        """Send work back to the developer (or admin for declarative-only changes)."""
        target = "developer" if (state.get("has_dev") or upd.get("has_dev")) else "admin"
        upd["rework_target"] = target
        upd["rework_text"] = f"Fix the following issues:\n\n{reason}"
        upd["uat_valid"] = False  # any change after UAT invalidates it
        upd["testing_done"] = False
        if not auto:
            upd["human_rework_count"] = int(state.get("human_rework_count") or 0) + 1

    # ------------------------------------------------------- agent execution

    async def run_agent(
        state: dict,
        upd: dict,
        *,
        node: str,
        role: str,
        step: str,
        thread_key: str,
        task: str | None,
        record_user: bool,
        server: str | None = None,
        extra: tuple[tuple[str, str], ...] = (),
        output_key: str | None = None,
    ) -> str | None:
        """Run one agent turn. Returns the final text, or ``None`` when a limit /
        tools-unavailable gate was opened instead (caller just returns ``upd``)."""
        spec = AGENTS[role]
        sid = state["session_id"]
        await publish({**state, **upd}, step, agent=spec.agent_id, status="in_progress")

        try:
            tools = await deps.tools(server or spec.server, spec.tools)
        except McpUnavailable as exc:
            await open_gate(
                state,
                upd,
                agent=spec.agent_id,
                name="tools_unavailable",
                question=(
                    f"{spec.agent_id} cannot start: {exc}\n\n"
                    "Fix the toolkit (deployment / URL / credentials), then choose:\n"
                    "[R] Retry\n[C] Cancel the pipeline\nYour choice:"
                ),
                step=step,
                resume_node=node,
                emit_turn=True,
            )
            return None

        outputs = {**(state.get("outputs") or {}), **(upd.get("outputs") or {})}
        system = render_system_prompt(role, session_id=sid, outputs=outputs, extra_sections=extra)
        thread = (upd.get("threads") or {}).get(thread_key) or (state.get("threads") or {}).get(thread_key) or []

        if record_user and task:
            await say(state, spec.agent_id, task, step, role="user")

        async def on_activity(text: str) -> None:
            await say(state, spec.agent_id, text, step, role="activity")

        try:
            new_thread, text = await run_turn(
                llm=deps.llm(spec.tier),
                tools=tools,
                system_prompt=system,
                thread=thread,
                user_text=task,
                max_iterations=spec.max_iterations,
                on_activity=on_activity,
            )
        except AgentIterationLimit as lim:
            upd["threads"] = {**(upd.get("threads") or {}), thread_key: lim.thread}
            await open_gate(
                state,
                upd,
                agent=spec.agent_id,
                name="limit",
                question=(
                    f"{spec.agent_id} used its tool-call budget ({lim.limit} model calls) without finishing this step.\n\n"
                    "[R] Retry (continue where it left off)\n[C] Cancel the pipeline\nYour choice:"
                ),
                step=step,
                resume_node=node,
                emit_turn=True,
            )
            return None

        upd["threads"] = {**(upd.get("threads") or {}), thread_key: new_thread}
        await say(state, spec.agent_id, text, step)
        await deps.store.record_handoff(sid, spec.agent_id, BACKEND_AGENT, {"step": step, "output": text})
        if output_key:
            upd["outputs"] = {**(upd.get("outputs") or {}), output_key: text}
        return text

    async def agent_step(
        state: dict,
        *,
        node: str,
        role: str,
        step: str,
        thread_key: str,
        task_fn: Callable[[], str],
        server: str | None = None,
        extra: tuple[tuple[str, str], ...] = (),
        output_key: str | None = None,
        fresh: bool | None = None,
    ) -> tuple[dict, str | None]:
        """Generic agent node body: first run, or resume after one of this node's gates.

        Returns ``(update, final_text)``; ``final_text`` is ``None`` when the node
        opened a gate or aborted, in which case the caller simply returns ``update``.
        """
        upd: dict[str, Any] = {}
        spec = AGENTS[role]
        ans = None if fresh else answer_for(state, node)
        if ans:
            consume(upd)
        task: str | None
        record_user = False
        if ans is None:
            task, record_user = task_fn(), True
        else:
            name, text = ans["gate_name"], ans["text"]
            if name in ("limit", "tools_unavailable") and choice(text) == "c":
                abort(upd, f"cancelled at {spec.agent_id}")
                return upd, None
            if name == "limit":
                task = None  # continue the same thread
            elif name == "tools_unavailable":
                task, record_user = task_fn(), True
            else:  # the agent's own gate: its answer goes back to the agent verbatim
                task = text
        text_out = await run_agent(
            state,
            upd,
            node=node,
            role=role,
            step=step,
            thread_key=thread_key,
            task=task,
            record_user=record_user,
            server=server,
            extra=extra,
            output_key=output_key,
        )
        if text_out is None:
            return upd, None
        if spec.can_gate and looks_like_gate(text_out):
            await open_gate(
                state,
                upd,
                agent=spec.agent_id,
                name="agent_gate",
                question=text_out,
                step=step,
                resume_node=node,
                emit_turn=False,
            )
            return upd, None
        return upd, text_out

    # ----------------------------------------------------------------- design

    def apply_plan(upd: dict, admin: str | None, dev: str | None) -> None:
        upd.update(
            admin_prompt=admin,
            dev_prompt=dev,
            has_admin=bool(admin),
            has_dev=bool(dev),
            admin_done=False,
            dev_done=False,
            testing_done=False,
            design_done=False,
        )

    async def design(state: dict) -> dict:
        node, role, step = "design", "design", "design"
        spec = AGENTS[role]
        upd: dict[str, Any] = {}
        ans = answer_for(state, node)
        task: str | None = None
        record_user = False
        retried = False
        if ans:
            consume(upd)
            name, text, c = ans["gate_name"], ans["text"], choice(ans["text"])
            if name in ("limit", "tools_unavailable") and c == "c":
                abort(upd, "cancelled at design")
                return upd
            if name == "limit":
                task = None
            elif name == "tools_unavailable":
                task, record_user = state["request"], True
            elif name == "design_failed":
                if c == "c":
                    abort(upd, "cancelled at design")
                    return upd
                if c == "p":
                    admin, dev = parse_design_plan(text)
                    if admin or dev:
                        apply_plan(upd, admin, dev)
                        upd["design_done"] = True  # the human wrote the plan: no second confirmation
                        return upd
                    await open_gate(
                        state,
                        upd,
                        agent=spec.agent_id,
                        name="design_failed",
                        question=(
                            "That text didn't include a parseable ADMIN PROMPT:/DEV PROMPT: block (each wrapped in "
                            "triple quotes). Try again, retry the agent, or cancel.\n\n"
                            "[R] Retry (re-ask the design agent)\n[P] Provide the plan yourself (paste both blocks "
                            "in the note box)\n[C] Cancel"
                        ),
                        step=step,
                        resume_node=node,
                        emit_turn=True,
                    )
                    return upd
                task = _DESIGN_NUDGE if (c == "r" and len(text.strip()) <= 3) else text
            elif name == "design_confirm":
                reply = parse_design_reply(text)
                if reply == "no":
                    abort(upd, "plan rejected at design confirmation")
                    return upd
                if reply == "yes":
                    upd["design_done"] = True  # the plan was parsed and stored when the gate opened
                    return upd
                task = text  # "changes": the instructions go back to the design agent
            else:  # agent_gate: a clarifying question the design agent asked
                task = text
        else:
            task, record_user = state["request"], True

        while True:
            text_out = await run_agent(
                state,
                upd,
                node=node,
                role=role,
                step=step,
                thread_key="design",
                task=task,
                record_user=record_user,
                output_key="design",
            )
            if text_out is None:
                return upd
            upd["design_message"] = text_out
            admin, dev = parse_design_plan(text_out)
            if admin or dev:
                apply_plan(upd, admin, dev)
                if not deps.require_design_confirmation:
                    upd["design_done"] = True
                    return upd
                if has_yes_no_changes(text_out):  # the agent already asked it
                    await open_gate(state, upd, agent=spec.agent_id, name="design_confirm", question=text_out, step=step, resume_node=node, emit_turn=False)
                else:
                    await open_gate(state, upd, agent=spec.agent_id, name="design_confirm", question=Q_DESIGN_CONFIRM, step=step, resume_node=node, emit_turn=True)
                return upd
            if looks_like_gate(text_out) or ends_with_question(text_out):
                await open_gate(state, upd, agent=spec.agent_id, name="agent_gate", question=text_out, step=step, resume_node=node, emit_turn=False)
                return upd
            if not retried:  # one automatic nudge before bothering the human
                retried = True
                task, record_user = _DESIGN_NUDGE, True
                continue
            await open_gate(
                state,
                upd,
                agent=spec.agent_id,
                name="design_failed",
                question=(
                    "The design agent did not produce a usable ADMIN WORK / DEV WORK plan for this request -- see its "
                    "output above. It was retried automatically once already.\n\n"
                    "[R] Retry (re-ask the design agent)\n[P] Provide the plan yourself (paste your ADMIN PROMPT:/DEV "
                    "PROMPT: blocks, in triple quotes, in the note box)\n[C] Cancel"
                ),
                step=step,
                resume_node=node,
                emit_turn=True,
            )
            return upd

    # ------------------------------------------------------------- build/test

    async def admin(state: dict) -> dict:
        rework = state.get("rework_target") == "admin"
        upd, text = await agent_step(
            state,
            node="admin",
            role="admin",
            step="build",
            thread_key="admin",
            task_fn=lambda: (state.get("rework_text") if rework else state.get("admin_prompt")) or "",
            output_key="admin",
        )
        if text is not None:
            upd["admin_done"] = True
        return upd

    async def developer(state: dict) -> dict:
        rework = state.get("rework_target") == "developer"
        upd, text = await agent_step(
            state,
            node="developer",
            role="developer",
            step="build",
            thread_key="developer",
            task_fn=lambda: (state.get("rework_text") if rework else state.get("dev_prompt")) or "",
            output_key="developer",
        )
        if text is not None:
            upd["dev_done"] = True
        return upd

    async def unit_testing(state: dict) -> dict:
        reworked = bool(state.get("rework_target")) or bool(state.get("rework_count")) or bool(state.get("human_rework_count"))
        upd, text = await agent_step(
            state,
            node="unit_testing",
            role="unit_testing",
            step="test",
            thread_key="unit_testing",
            task_fn=lambda: _UNIT_TEST_TASK + (_UNIT_TEST_REWORK_SUFFIX if reworked else ""),
            output_key="unit_testing",
        )
        if text is not None:
            upd["testing_done"] = True
        return upd

    # ----------------------------------------------------------------- review

    def review_inline(state: dict) -> str:
        outputs = state.get("outputs") or {}
        parts = [
            f"=== {label} AGENT OUTPUT ===\n{outputs[key]}"
            for label, key in (("ADMIN", "admin"), ("DEV", "developer"), ("TESTS", "unit_testing"))
            if outputs.get(key)
        ]
        return "\n\n".join(parts) if parts else "No admin/dev output was produced for this request."

    async def code_review(state: dict) -> dict:
        node, step = "code_review", "review"
        spec = AGENTS["code_review"]
        ans = answer_for(state, node)
        if ans and ans["gate_name"] == "review_escalation":
            upd: dict[str, Any] = {}
            consume(upd)
            c = choice(ans["text"])
            if c == "f":
                start_rework(state, upd, (state.get("outputs") or {}).get("code_review", ""), auto=False)
            elif c == "s":
                upd["review_warning"] = True
                upd["rework_target"] = None
            elif c == "c":
                abort(upd, "cancelled at code-review escalation")
            else:
                await open_gate(state, upd, agent=spec.agent_id, name="review_escalation", question=_OPTIONS_HINT + ans.get("question", ""), step=step, resume_node=node, emit_turn=True)
            return upd

        upd, text = await agent_step(
            state,
            node=node,
            role="code_review",
            step=step,
            thread_key="code_review",
            task_fn=lambda: "Review the following work produced in this session:\n\n" + review_inline(state),
            output_key="code_review",
        )
        if text is None:
            return upd
        upd["rework_target"] = None  # a fresh review supersedes any pending rework marker
        upd["rework_text"] = None
        verdict = parse_code_review_verdict(text)
        upd["code_review_verdict"] = verdict
        if verdict_passes(verdict):
            return upd
        count = int(state.get("rework_count") or 0)
        if count < deps.max_rework_loops:
            upd["rework_count"] = count + 1
            start_rework(state, upd, text, auto=True)
            await say(
                state,
                BACKEND_AGENT,
                f"Code review verdict: {VERDICT_LABELS.get(verdict, verdict)}. Automatic rework loop "
                f"{count + 1} of {deps.max_rework_loops}: sending the findings back to the {upd['rework_target']} agent.",
                step,
            )
            return upd
        question = (
            text.rstrip()
            + f"\n\nThe automatic rework cap ({deps.max_rework_loops} loops) has been reached (G6).\n"
            "[F] Fix (one more rework round)\n[S] Skip (proceed with the warning noted)\n[C] Cancel\nYour choice:"
        )
        await open_gate(state, upd, agent=spec.agent_id, name="review_escalation", question=question, step=step, resume_node=node, emit_turn=True)
        return upd

    # ----------------------------------------------------------------- commit

    async def github_commit(state: dict) -> dict:
        node, step = "github_commit", "commit"
        spec = AGENTS["github_commit"]
        ans = answer_for(state, node)
        pre: dict[str, Any] = {}
        force_fresh = False
        if ans and ans["gate_name"] == "commit_outcome":
            consume(pre)
            c = choice(ans["text"])
            if c == "r":
                force_fresh = True
            elif c == "c":
                abort(pre, "cancelled after the commit step did not complete")
                return pre
            else:
                await open_gate(state, pre, agent=spec.agent_id, name="commit_outcome", question=_OPTIONS_HINT + ans.get("question", ""), step=step, resume_node=node, emit_turn=True)
                return pre
        fresh = ans is None or force_fresh
        run = int(state.get("commit_run") or 0) + (1 if fresh else 0)
        upd, text = await agent_step(
            state,
            node=node,
            role="github_commit",
            step=step,
            thread_key=f"github_commit#{run}",
            task_fn=lambda: _COMMIT_GOAL,
            output_key="github_commit",
            fresh=True if force_fresh else None,
        )
        upd = {**pre, **upd, "commit_run": run}
        if text is None:
            return upd
        status = parse_commit_status(text)
        if status in ("failed", "cancelled"):
            await open_gate(
                state,
                upd,
                agent=spec.agent_id,
                name="commit_outcome",
                question=(
                    f"The commit agent reported its commit as {status.upper()}, so nothing new is ready to deploy "
                    "from git.\n\n[R] Re-run the commit step\n[C] Cancel the pipeline\nYour choice:"
                ),
                step=step,
                resume_node=node,
                emit_turn=True,
            )
        return upd

    # ----------------------------------------------------------------- deploy

    def deploy_node(
        *,
        node: str,
        step: str,
        run_key: str,
        thread_prefix: str,
        server: str,
        output_key: str,
        stage_note: str,
        stage_label: str,
        fix_letters: str,
        fix_word: str,
    ) -> Callable[[dict], Awaitable[dict]]:
        spec = AGENTS["devops"]

        async def fn(state: dict) -> dict:
            ans = answer_for(state, node)
            pre: dict[str, Any] = {}
            force_fresh = False
            if ans and ans["gate_name"] == "deploy_outcome":
                consume(pre)
                c = choice(ans["text"])
                if c == "r":
                    force_fresh = True
                elif c and c in fix_letters:
                    start_rework(state, pre, (state.get("outputs") or {}).get(output_key, ""), auto=False)
                    return pre
                elif c == "c":
                    abort(pre, f"cancelled after a failed {stage_label} deployment")
                    return pre
                else:  # unrecognised input never aborts: ask again
                    await open_gate(
                        state,
                        pre,
                        agent=spec.agent_id,
                        name="deploy_outcome",
                        question=_OPTIONS_HINT + ans.get("question", ""),
                        step=step,
                        resume_node=node,
                        emit_turn=True,
                    )
                    return pre
            fresh = ans is None or force_fresh
            run = int(state.get(run_key) or 0) + (1 if fresh else 0)
            upd, text = await agent_step(
                state,
                node=node,
                role="devops",
                step=step,
                thread_key=f"{thread_prefix}#{run}",
                task_fn=lambda: f"Deploy the components produced and approved in this session to the {stage_label} org.",
                server=server,
                extra=(("Deployment stage", stage_note),),
                output_key=output_key,
                fresh=True if force_fresh else None,
            )
            upd = {**pre, **upd, run_key: run}
            if text is None:
                return upd
            status = parse_deploy_status(text)
            if status in ("failed", "blocked", "cancelled"):
                if status == "cancelled":
                    options = "[R] Re-run the deployment\n[C] Cancel the pipeline\n"
                else:
                    options = f"[R] Retry the deployment\n[{fix_letters[0].upper()}] {fix_word} (send back to the developer)\n[C] Cancel the pipeline\n"
                await open_gate(
                    state,
                    upd,
                    agent=spec.agent_id,
                    name="deploy_outcome",
                    question=f"The {stage_label} deployment was reported as {status.upper()}.\n\n{options}Your choice:",
                    step=step,
                    resume_node=node,
                    emit_turn=True,
                )
            return upd

        return fn

    qa_deploy = deploy_node(
        node="qa_deploy",
        step="qa_deploy",
        run_key="qa_run",
        thread_prefix="devops_qa",
        server=SRV_SALESFORCE_QA,
        output_key="devops_qa",
        stage_note=(
            "QA. Your tools are connected to the QA org. This is the first of two deployments in this session; "
            "Prod is deployed separately, later, only after human approvals. Never deploy anywhere else."
        ),
        stage_label="QA",
        fix_letters="f",
        fix_word="Fix",
    )
    prod_deploy = deploy_node(
        node="prod_deploy",
        step="prod_deploy",
        run_key="prod_run",
        thread_prefix="devops_prod",
        server=SRV_SALESFORCE_PROD,
        output_key="devops_prod",
        stage_note=(
            "PROD. Your tools are connected to the production org. The QA deployment, SME confirmation, UAT, PR "
            "approval and merge have all been completed and recorded by humans. Deploy exactly the approved "
            "components and nothing else."
        ),
        stage_label="Prod",
        fix_letters="h",
        fix_word="Hotfix",
    )

    # ------------------------------------------------------------ human gates

    def human_gate(
        node: str,
        step: str,
        gate_name: str,
        question: str,
        handle: Callable[[dict, dict, str, str], str | None],
        agent: str = BACKEND_AGENT,
    ) -> Callable[[dict], Awaitable[dict]]:
        async def fn(state: dict) -> dict:
            upd: dict[str, Any] = {}
            ans = answer_for(state, node)
            if ans is None:
                await open_gate(state, upd, agent=agent, name=gate_name, question=question, step=step, resume_node=node, emit_turn=True)
                return upd
            consume(upd)
            if handle(state, upd, choice(ans["text"]), ans["text"]) == "reopen":
                await open_gate(state, upd, agent=agent, name=gate_name, question=_OPTIONS_HINT + question, step=step, resume_node=node, emit_turn=True)
            return upd

        return fn

    def on_qa_confirm(state: dict, upd: dict, c: str, text: str) -> str | None:
        if c == "y":
            return None
        if c == "f":
            start_rework(state, upd, f"The QA SME reported the change is not complete or not correct.\n\n{text}", auto=False)
            return None
        if c == "c":
            abort(upd, "cancelled at QA confirmation")
            return None
        return "reopen"

    def on_uat(state: dict, upd: dict, c: str, text: str) -> str | None:
        if c == "y":
            upd["uat_valid"] = True
            return None
        if c == "r":
            start_rework(state, upd, f"UAT was rejected.\n\n{text}", auto=False)
            return None
        if c == "c":
            abort(upd, "cancelled at UAT approval")
            return None
        return "reopen"

    def on_pr(state: dict, upd: dict, c: str, text: str) -> str | None:
        if c == "y":
            return None
        if c == "r":
            start_rework(state, upd, f"The tech lead requested changes on the pull request.\n\n{text}", auto=False)
            return None
        if c == "c":
            abort(upd, "cancelled at PR approval")
            return None
        return "reopen"

    def on_merge(state: dict, upd: dict, c: str, text: str) -> str | None:
        if c == "m":
            return None
        if c == "c":
            abort(upd, "cancelled before merge")
            return None
        return "reopen"

    qa_confirm = human_gate("qa_confirm", "qa_confirm", "qa_confirm", Q_QA_CONFIRM, on_qa_confirm)
    uat_approval = human_gate("uat_approval", "uat", "uat_approval", Q_UAT, on_uat)
    pr_approval = human_gate("pr_approval", "pr_approval", "pr_approval", Q_PR, on_pr)
    merge_confirm = human_gate("merge_confirm", "merge", "merge_confirm", Q_MERGE, on_merge)

    async def prod_preflight(state: dict) -> dict:
        """Deterministic guard (no LLM): Prod is reachable only after every human gate is on record."""
        node, step = "prod_preflight", "prod_preflight"
        upd: dict[str, Any] = {}
        ans = answer_for(state, node)
        if ans:
            consume(upd)
            c = choice(ans["text"])
            if c == "c":
                abort(upd, "cancelled at Prod pre-flight")
                return upd
            # anything else (including "R") simply re-runs the check below
        await publish({**state, **upd}, step, agent=BACKEND_AGENT, status="in_progress")
        gates = await deps.store.list_gates(state["session_id"])
        problems = prod_preflight_problems(gates, uat_valid=bool(state.get("uat_valid")))
        if problems:
            question = (
                "Prod pre-flight blocked. Prod will not be touched until this is resolved:\n- "
                + "\n- ".join(problems)
                + "\n\n[R] Re-check\n[C] Cancel the pipeline\nYour choice:"
            )
            await open_gate(state, upd, agent=BACKEND_AGENT, name="prod_preflight_blocked", question=question, step=step, resume_node=node, emit_turn=True)
            return upd
        await say(
            state,
            BACKEND_AGENT,
            "Prod pre-flight passed: QA confirmation, UAT approval, PR approval and merge are all recorded with a human identity.",
            step,
        )
        return upd

    async def prod_confirm(state: dict) -> dict:
        node, step = "prod_confirm", "prod_confirm"
        upd: dict[str, Any] = {}
        ans = answer_for(state, node)
        if ans is None:
            await open_gate(state, upd, agent=BACKEND_AGENT, name="prod_confirm", question=Q_PROD_CONFIRM, step=step, resume_node=node, emit_turn=True)
            return upd
        consume(upd)
        c = choice(ans["text"])
        if ans["gate_name"] == "prod_confirm":
            if c == "y":
                return upd
            if c == "n":
                await open_gate(state, upd, agent=BACKEND_AGENT, name="prod_escalation", question=Q_PROD_ESCALATION, step=step, resume_node=node, emit_turn=True)
                return upd
            await open_gate(state, upd, agent=BACKEND_AGENT, name="prod_confirm", question=_OPTIONS_HINT + Q_PROD_CONFIRM, step=step, resume_node=node, emit_turn=True)
            return upd
        # prod_escalation (G6): a human decides; no agent self-heals Prod
        if c == "h":
            start_rework(state, upd, f"Prod was reported incorrect; a hotfix is required.\n\n{ans['text']}", auto=False)
        elif c == "r":
            abort(upd, "Prod rolled back manually (G6)")
        elif c == "c":
            abort(upd, "cancelled at Prod escalation (G6)")
        else:
            await open_gate(state, upd, agent=BACKEND_AGENT, name="prod_escalation", question=_OPTIONS_HINT + Q_PROD_ESCALATION, step=step, resume_node=node, emit_turn=True)
        return upd

    # ------------------------------------------------------------- docs steps

    async def docs_preflight(state: dict) -> dict:
        node, step = "docs_preflight", "docs_preflight"
        upd: dict[str, Any] = {}
        ans = answer_for(state, node)

        async def ask(substep: str, question: str) -> dict:
            upd["docs_substep"] = substep
            await open_gate(state, upd, agent=BACKEND_AGENT, name=f"docs_preflight_{substep}", question=question, step=step, resume_node=node, emit_turn=True)
            return upd

        if ans is None:
            return await ask("q1", Q_DOCS_Q1)
        consume(upd)
        sub, text, c = state.get("docs_substep") or "q1", ans["text"], choice(ans["text"])
        if sub == "q1":
            if c not in ("c", "l", "s"):
                return await ask("q1", _OPTIONS_HINT + Q_DOCS_Q1)
            upd["docs_destination"] = c
            upd["skip_docs"] = c == "s"
            if c == "s":
                return upd
            return await ask("local_format", Q_DOCS_LOCAL) if c == "l" else await ask("new_or_existing", Q_DOCS_NEW_OR_EXISTING)
        if sub == "local_format":
            upd["docs_local_format"] = text.strip()
            return upd
        if sub == "new_or_existing":
            if c not in ("n", "e"):
                return await ask("new_or_existing", _OPTIONS_HINT + Q_DOCS_NEW_OR_EXISTING)
            upd["docs_confluence_new"] = c == "n"
            return await ask("location", Q_DOCS_LOCATION)
        upd["docs_confluence_location"] = text.strip()
        return upd

    async def documentation(state: dict) -> dict:
        upd, _ = await agent_step(
            state,
            node="documentation",
            role="documentation",
            step="docs",
            thread_key="documentation",
            task_fn=lambda: build_docs_prompt(state),
            output_key="documentation",
        )
        return upd

    # --------------------------------------------------------- gate + finish

    async def gate_wait(state: dict) -> dict:
        """Pure human-gate node: no LLM, no tools, no side effects before interrupt()."""
        gate = state.get("gate")
        if not gate:
            raise RuntimeError("gate_wait entered without an open gate")
        payload = interrupt(
            {"gate_id": gate["gate_id"], "agent": gate["agent"], "name": gate["name"], "question": gate["question"], "step": gate["step"]}
        )
        if (
            not isinstance(payload, dict)
            or payload.get("source") not in ("api", "webhook")
            or not str(payload.get("answered_by") or "").strip()
            or not str(payload.get("text") or "").strip()
            or payload.get("gate_id") != gate["gate_id"]
        ):
            # Agent output, a stale reply, or an unstamped payload can never answer a gate.
            raise ValueError("rejected gate answer: not stamped by the API/webhook layer for this gate")
        return {
            "gate": None,
            "gate_answer": {"text": payload["text"], "answered_by": payload["answered_by"], "gate_name": gate["name"], "question": gate["question"]},
        }

    async def finish(state: dict) -> dict:
        sid = state["session_id"]
        status = state.get("final_status") or "complete"
        if status == "complete":
            outputs = state.get("outputs") or {}
            verdict = VERDICT_LABELS.get(state.get("code_review_verdict", "unknown"), state.get("code_review_verdict", "unknown"))
            summary = (
                "Pipeline complete.\n"
                f"- Code review: {verdict} (automatic rework loops: {int(state.get('rework_count') or 0)}, "
                f"human-requested: {int(state.get('human_rework_count') or 0)})\n"
                "- Commit & PR: done\n"
                "- QA: deployed and confirmed; UAT approved\n"
                f"- Prod: {'deployed and confirmed' if outputs.get('devops_prod') else 'not deployed'}\n"
                f"- Documentation: {'skipped' if state.get('skip_docs') else 'done'}"
            )
            await say(state, BACKEND_AGENT, summary, "complete")
            ctx = {k: state.get(k) for k in _UI_CONTEXT_KEYS if state.get(k) is not None}
            await deps.store.set_ui_state(sid, {"step": "complete", "active_agents": [], "context": ctx})
            await deps.store.set_status(sid, "complete", current_agent=None)
        else:
            session = await deps.store.get_session(sid)
            step = ((session or {}).get("pipeline_state") or {}).get("step") or "design"
            await say(state, BACKEND_AGENT, f"Pipeline stopped: {state.get('final_note') or 'aborted'}.", step)
            ctx = {k: state.get(k) for k in _UI_CONTEXT_KEYS if state.get(k) is not None}
            await deps.store.set_ui_state(sid, {"step": step, "active_agents": [], "context": ctx})
            await deps.store.set_status(sid, "aborted", current_agent=None)
        return {}

    # ------------------------------------------------------------------ wiring

    def bug(msg: str):
        raise RuntimeError(f"routing error: {msg}")

    def router(next_fn: Callable[[dict], str]) -> Callable[[dict], str]:
        def route(state: dict) -> str:
            if state.get("gate"):
                return "gate_wait"
            if state.get("final_status"):
                return "finish"
            return next_fn(state)

        return route

    def rework_or(default: str) -> Callable[[dict], str]:
        return lambda s: s["rework_target"] if s.get("rework_target") else default

    def after_design(s: dict) -> str:
        if not s.get("design_done"):
            bug("design finished without a confirmed plan")
        return "admin" if s.get("has_admin") else "developer"

    def after_admin(s: dict) -> str:
        if s.get("rework_target") == "admin":
            return "code_review"
        return "developer" if s.get("has_dev") else "code_review"

    def after_docs_preflight(s: dict) -> str:
        return "finish" if s.get("skip_docs") else "documentation"

    g = StateGraph(OrbitState)
    nodes: dict[str, Callable] = {
        "design": design,
        "admin": admin,
        "developer": developer,
        "unit_testing": unit_testing,
        "code_review": code_review,
        "github_commit": github_commit,
        "qa_deploy": qa_deploy,
        "qa_confirm": qa_confirm,
        "uat_approval": uat_approval,
        "pr_approval": pr_approval,
        "merge_confirm": merge_confirm,
        "prod_preflight": prod_preflight,
        "prod_deploy": prod_deploy,
        "prod_confirm": prod_confirm,
        "docs_preflight": docs_preflight,
        "documentation": documentation,
        "gate_wait": gate_wait,
        "finish": finish,
    }
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "design")

    # node -> (next-function, every possible destination)
    flow: dict[str, tuple[Callable[[dict], str], list[str]]] = {
        "design": (after_design, ["admin", "developer"]),
        "admin": (after_admin, ["developer", "code_review"]),
        "developer": (lambda s: "unit_testing", ["unit_testing"]),
        "unit_testing": (lambda s: "code_review", ["code_review"]),
        "code_review": (lambda s: s["rework_target"] if s.get("rework_target") else "github_commit", ["developer", "admin", "github_commit"]),
        "github_commit": (lambda s: "qa_deploy", ["qa_deploy"]),
        "qa_deploy": (rework_or("qa_confirm"), ["qa_confirm", "developer", "admin"]),
        "qa_confirm": (rework_or("uat_approval"), ["uat_approval", "developer", "admin"]),
        "uat_approval": (rework_or("pr_approval"), ["pr_approval", "developer", "admin"]),
        "pr_approval": (rework_or("merge_confirm"), ["merge_confirm", "developer", "admin"]),
        "merge_confirm": (lambda s: "prod_preflight", ["prod_preflight"]),
        "prod_preflight": (lambda s: "prod_deploy", ["prod_deploy"]),
        "prod_deploy": (rework_or("prod_confirm"), ["prod_confirm", "developer", "admin"]),
        "prod_confirm": (rework_or("docs_preflight"), ["docs_preflight", "developer", "admin"]),
        "docs_preflight": (after_docs_preflight, ["documentation", "finish"]),
        "documentation": (lambda s: "finish", ["finish"]),
    }
    for name, (next_fn, dests) in flow.items():
        g.add_conditional_edges(name, router(next_fn), sorted({*dests, "gate_wait", "finish"}))

    resumable = [n for n in flow]  # every node that can open a gate
    g.add_conditional_edges("gate_wait", lambda s: s["resume_node"], resumable)
    g.add_edge("finish", END)
    return g
