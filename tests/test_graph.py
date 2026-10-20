"""End-to-end graph tests with a scripted fake model (no network, no Postgres).

Requires the runtime dependencies (langgraph, langchain-core); skipped otherwise.
Run:  python -m unittest discover -s tests -v
"""
import importlib.util
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("langgraph", "langchain_core"))

if HAVE_DEPS:
    from langchain_core.messages import AIMessage
    from langgraph.types import Command

    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:  # older langgraph
        from langgraph.checkpoint.memory import MemorySaver as InMemorySaver

    from sdlc_orbit.graph import Deps, build_graph
    from sdlc_orbit.mcp_tools import McpUnavailable

PLAN = (
    '\U0001F4DD ADMIN PROMPT:\n"""\nCreate Foo__c\n"""\n\n'
    '\U0001F4DD DEV PROMPT:\n"""\nCreate FooService\n"""\n'
)
M_DESIGN = "# Salesforce Design Agent"
M_ADMIN = "# Salesforce Admin Agent"
M_DEV = "# Salesforce Developer Agent"
M_TEST = "# Salesforce Unit Testing Agent"
M_REVIEW = "# Salesforce Code Review Agent"
M_COMMIT = "# GitHub Deployment Agent"
M_OPS = "# Salesforce DevOps Agent"
M_DOCS = "# Salesforce Documentation Agent"


def happy_scripts():
    return {
        M_DESIGN: [PLAN],
        M_ADMIN: ["Admin done"],
        M_DEV: ["Dev done"],
        M_TEST: ["Tests done"],
        M_REVIEW: ["## Verdict: APPROVED"],
        M_COMMIT: ["Manual change review\n[Y] YES\n[N] NO", "## Commit\nStatus: SUCCESS\nPR opened"],
        M_OPS: ["Status: SUCCESS"],
        M_DOCS: ["Documentation published"],
    }


if HAVE_DEPS:

    class FakeChat:
        """Picks a scripted reply by the agent heading found in the system prompt.
        The last reply of a script repeats once the script is exhausted."""

        def __init__(self, scripts):
            self.scripts = {k: list(v) for k, v in scripts.items()}
            self.calls = {k: 0 for k in scripts}

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            system = messages[0].content
            hits = [(system.find(m), m) for m in self.scripts if m in system]
            assert hits, "no scripted agent matches this system prompt"
            marker = min(hits)[1]
            queue = self.scripts[marker]
            self.calls[marker] += 1
            return AIMessage(content=queue.pop(0) if len(queue) > 1 else queue[0])

    class FakeStore:
        def __init__(self):
            self.turns, self.gates, self.handoffs = [], [], []
            self.status, self.ui = {}, {}

        async def append_turn(self, sid, agent, role, content, step=None, stage=None):
            self.turns.append({"agent": agent, "role": role, "content": content, "step": step})

        async def record_gate(self, sid, agent, name, question):
            self.gates.append(
                {"id": len(self.gates) + 1, "agent_name": agent, "gate_name": name, "question": question, "answer": None, "answered_by": None}
            )
            return len(self.gates)

        async def set_ui_state(self, sid, state):
            self.ui[sid] = state

        async def set_status(self, sid, status, current_agent=None, error=None):
            self.status[sid] = status

        async def list_gates(self, sid):
            return list(self.gates)

        async def get_session(self, sid):
            return {"pipeline_state": self.ui.get(sid)}

        async def record_handoff(self, sid, a, b, payload):
            self.handoffs.append((a, b))

    class Harness:
        SID = "s1"

        def __init__(self, scripts, *, max_rework=3, prod_unavailable=False):
            self.store = FakeStore()
            self.llm = FakeChat(scripts)
            self.tool_calls = []

            async def tools(server, allow):
                self.tool_calls.append((server, tuple(allow)))
                if prod_unavailable and server == "salesforce_prod":
                    raise McpUnavailable("Prod toolkit is not configured")
                return []

            deps = Deps(llm=lambda tier: self.llm, tools=tools, store=self.store, max_rework_loops=max_rework)
            self.graph = build_graph(deps).compile(checkpointer=InMemorySaver())
            self.cfg = {"configurable": {"thread_id": self.SID}, "recursion_limit": 200}

        async def start(self, request="Add a field Foo__c"):
            await self.graph.ainvoke({"session_id": self.SID, "request": request}, self.cfg)

        async def gate(self):
            snap = await self.graph.aget_state(self.cfg)
            for task in snap.tasks:
                for itr in task.interrupts:
                    return itr.value
            return None

        async def values(self):
            return (await self.graph.aget_state(self.cfg)).values

        async def answer(self, text, *, by="tester@lilly.com", source="api"):
            payload = await self.gate()
            assert payload is not None, "no gate is open"
            for g in self.store.gates:
                if g["id"] == payload["gate_id"]:
                    g["answer"], g["answered_by"] = text, by
            await self.graph.ainvoke(
                Command(resume={"text": text, "answered_by": by, "gate_id": payload["gate_id"], "source": source}), self.cfg
            )

        async def expect_and_answer(self, name, text):
            payload = await self.gate()
            assert payload is not None, f"expected gate {name!r} but the graph is not paused"
            assert payload["name"] == name, f"expected gate {name!r}, got {payload['name']!r}"
            await self.answer(text)


@unittest.skipUnless(HAVE_DEPS, "langgraph / langchain-core not installed")
class GraphFlow(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_through_every_gate(self):
        h = Harness(happy_scripts())
        await h.start()
        for name, text in [
            ("design_confirm", "yes"),
            ("agent_gate", "Y"),  # commit agent's own Gate 1
            ("qa_confirm", "y"),
            ("uat_approval", "y"),
            ("pr_approval", "y"),
            ("merge_confirm", "m"),
            ("prod_confirm", "y"),
            ("docs_preflight_q1", "c"),
            ("docs_preflight_new_or_existing", "n"),
            ("docs_preflight_location", "LSC/Design"),
        ]:
            await h.expect_and_answer(name, text)
        self.assertIsNone(await h.gate())
        self.assertEqual(h.store.status[h.SID], "complete")
        # every gate has a human identity recorded
        self.assertTrue(all(g["answer"] and g["answered_by"] for g in h.store.gates))
        # least privilege + QA/Prod separation
        servers = [s for s, _ in h.tool_calls]
        self.assertIn("salesforce_qa", servers)
        self.assertIn("salesforce_prod", servers)
        self.assertLess(servers.index("salesforce_qa"), servers.index("salesforce_prod"))
        self.assertIn(("confluence", ("search_content", "get_page")), h.tool_calls)

    async def test_skip_docs_finishes_without_documentation_agent(self):
        h = Harness(happy_scripts())
        await h.start()
        for name, text in [
            ("design_confirm", "yes"), ("agent_gate", "Y"), ("qa_confirm", "y"), ("uat_approval", "y"),
            ("pr_approval", "y"), ("merge_confirm", "m"), ("prod_confirm", "y"), ("docs_preflight_q1", "s"),
        ]:
            await h.expect_and_answer(name, text)
        self.assertEqual(h.store.status[h.SID], "complete")
        self.assertEqual(h.llm.calls[M_DOCS], 0)

    async def test_design_changes_reasks_the_agent(self):
        scripts = happy_scripts()
        scripts[M_DESIGN] = [PLAN, PLAN]
        h = Harness(scripts)
        await h.start()
        await h.expect_and_answer("design_confirm", "changes: also add a validation rule")
        self.assertEqual(h.llm.calls[M_DESIGN], 2)
        self.assertEqual((await h.gate())["name"], "design_confirm")

    async def test_design_no_aborts(self):
        h = Harness(happy_scripts())
        await h.start()
        await h.expect_and_answer("design_confirm", "no")
        self.assertEqual(h.store.status[h.SID], "aborted")
        self.assertEqual(h.llm.calls[M_ADMIN], 0)

    async def test_design_without_plan_retries_once_then_asks_human(self):
        scripts = happy_scripts()
        scripts[M_DESIGN] = ["I cannot do this."]
        h = Harness(scripts)
        await h.start()
        self.assertEqual(h.llm.calls[M_DESIGN], 2)  # first try + one automatic nudge
        self.assertEqual((await h.gate())["name"], "design_failed")

    async def test_design_clarifying_question_is_not_overridden(self):
        scripts = happy_scripts()
        scripts[M_DESIGN] = ["Which queue should Web Form enrollments route to?", PLAN]
        h = Harness(scripts)
        await h.start()
        self.assertEqual(h.llm.calls[M_DESIGN], 1)  # no forced retry over a legitimate question
        await h.expect_and_answer("agent_gate", "The Zepbound welcome queue")
        self.assertEqual((await h.gate())["name"], "design_confirm")

    async def test_review_rejection_loops_back_automatically(self):
        scripts = happy_scripts()
        scripts[M_REVIEW] = ["## Verdict: CHANGES REQUIRED\n1. SOQL in loop", "## Verdict: APPROVED"]
        h = Harness(scripts)
        await h.start()
        await h.expect_and_answer("design_confirm", "yes")
        self.assertEqual(h.llm.calls[M_DEV], 2)
        self.assertEqual(h.llm.calls[M_REVIEW], 2)
        self.assertEqual((await h.values())["rework_count"], 1)
        self.assertEqual((await h.gate())["name"], "agent_gate")  # on to the commit agent

    async def test_rework_cap_escalates_to_g6_and_cancel_aborts(self):
        scripts = happy_scripts()
        scripts[M_REVIEW] = ["## Verdict: CHANGES REQUIRED\n1. SOQL in loop"]
        h = Harness(scripts, max_rework=1)
        await h.start()
        await h.expect_and_answer("design_confirm", "yes")
        self.assertEqual((await h.gate())["name"], "review_escalation")
        await h.answer("c")
        self.assertEqual(h.store.status[h.SID], "aborted")

    async def test_unrecognised_review_verdict_never_counts_as_approval(self):
        scripts = happy_scripts()
        scripts[M_REVIEW] = ["NOT APPLICABLE - NOTHING TO REVIEW"]
        h = Harness(scripts, max_rework=0)
        await h.start()
        await h.expect_and_answer("design_confirm", "yes")
        self.assertEqual((await h.gate())["name"], "review_escalation")

    async def test_qa_fix_loops_back_and_invalidates_uat(self):
        h = Harness(happy_scripts())
        await h.start()
        await h.expect_and_answer("design_confirm", "yes")
        await h.expect_and_answer("agent_gate", "Y")
        await h.expect_and_answer("qa_confirm", "f: label is wrong")
        vals = await h.values()
        self.assertEqual(vals["commit_run"], 2)  # the commit step ran again
        self.assertFalse(vals["uat_valid"])
        self.assertEqual((await h.gate())["name"], "qa_confirm")

    async def test_prod_escalation_hotfix_repeats_the_chain(self):
        h = Harness(happy_scripts())
        await h.start()
        for name, text in [
            ("design_confirm", "yes"), ("agent_gate", "Y"), ("qa_confirm", "y"), ("uat_approval", "y"),
            ("pr_approval", "y"), ("merge_confirm", "m"), ("prod_confirm", "n"), ("prod_escalation", "h"),
        ]:
            await h.expect_and_answer(name, text)
        self.assertEqual((await h.gate())["name"], "qa_confirm")  # whole chain repeats; nothing self-heals Prod

    async def test_prod_fails_closed_when_its_toolkit_is_missing(self):
        h = Harness(happy_scripts(), prod_unavailable=True)
        await h.start()
        for name, text in [
            ("design_confirm", "yes"), ("agent_gate", "Y"), ("qa_confirm", "y"), ("uat_approval", "y"),
            ("pr_approval", "y"), ("merge_confirm", "m"),
        ]:
            await h.expect_and_answer(name, text)
        self.assertEqual((await h.gate())["name"], "tools_unavailable")
        await h.answer("c")
        self.assertEqual(h.store.status[h.SID], "aborted")

    async def test_unrecognised_answer_reasks_instead_of_proceeding(self):
        h = Harness(happy_scripts())
        await h.start()
        await h.expect_and_answer("design_confirm", "yes")
        await h.expect_and_answer("agent_gate", "Y")
        await h.expect_and_answer("qa_confirm", "banana")
        self.assertEqual((await h.gate())["name"], "qa_confirm")  # same gate again, nothing advanced

    async def test_forged_or_unstamped_gate_answer_is_rejected(self):
        h = Harness(happy_scripts())
        await h.start()
        gate = await h.gate()
        for bad in (
            {"text": "yes", "answered_by": "agent", "gate_id": gate["gate_id"], "source": "agent"},
            {"text": "yes", "answered_by": "", "gate_id": gate["gate_id"], "source": "api"},
            {"text": "yes", "answered_by": "u@lilly.com", "gate_id": 999, "source": "api"},
            "yes",
        ):
            with self.assertRaises(ValueError):
                await h.graph.ainvoke(Command(resume=bad), h.cfg)

    async def test_commit_failure_blocks_the_qa_deploy(self):
        scripts = happy_scripts()
        scripts[M_COMMIT] = ["## Commit\nStatus: FAILED\n"]
        h = Harness(scripts)
        await h.start()
        await h.expect_and_answer("design_confirm", "yes")
        self.assertEqual((await h.gate())["name"], "commit_outcome")
        self.assertEqual(h.llm.calls[M_OPS], 0)


if __name__ == "__main__":
    unittest.main()


if HAVE_DEPS:

    class FakeCortex:
        """Stands in for CortexClient: records calls, replies per registered agent id."""

        def __init__(self, scripts):
            self.scripts = {k: list(v) for k, v in scripts.items()}
            self.calls = []

        async def ask(self, agent, q, session_id, on_activity=None):
            self.calls.append((agent, q, session_id))
            queue = self.scripts[agent]
            return queue.pop(0) if len(queue) > 1 else queue[0]


@unittest.skipUnless(HAVE_DEPS, "langgraph / langchain-core not installed")
class CortexPrompt(unittest.IsolatedAsyncioTestCase):
    async def test_role_prompt_history_and_current_message_are_sent(self):
        from sdlc_orbit.agents import AGENTS, load_prompt

        design = AGENTS["design"].agent_id
        cortex = FakeCortex({design: ["no plan here", PLAN], **{a.agent_id: ["ok"] for k, a in AGENTS.items() if k != "design"}})
        store = FakeStore()
        g = build_graph(Deps(llm=lambda tier: None, tools=None, store=store, cortex=cortex)).compile(checkpointer=InMemorySaver())
        await g.ainvoke({"session_id": "c2", "request": "Add a Phone validation rule"}, {"configurable": {"thread_id": "c2"}, "recursion_limit": 200})

        first, second = [q for a, q, _ in cortex.calls if a == design][:2]
        self.assertIn(load_prompt("design").strip()[:200], first)
        self.assertTrue(first.rstrip().endswith("Add a Phone validation rule"))
        self.assertNotIn("CONVERSATION SO FAR", first)
        self.assertIn("CONVERSATION SO FAR", second)
        self.assertIn("no plan here", second)
        self.assertIn("Add a Phone validation rule", second)


@unittest.skipUnless(HAVE_DEPS, "langgraph / langchain-core not installed")
class CortexMode(unittest.IsolatedAsyncioTestCase):
    async def test_agents_run_on_cortex_by_registered_name(self):
        from sdlc_orbit.agents import AGENTS

        scripts = {
            AGENTS["design"].agent_id: [PLAN],
            AGENTS["admin"].agent_id: ["Admin done"],
            AGENTS["developer"].agent_id: ["Dev done"],
            AGENTS["unit_testing"].agent_id: ["Tests done"],
            AGENTS["code_review"].agent_id: ["## Verdict: APPROVED"],
            AGENTS["github_commit"].agent_id: ["Manual change review\n[Y] YES\n[N] NO", "Status: SUCCESS"],
            AGENTS["devops"].agent_id: ["Status: SUCCESS"],
            AGENTS["documentation"].agent_id: ["Documentation published"],
        }
        cortex = FakeCortex(scripts)
        store = FakeStore()

        async def no_local_tools(server, allow):
            raise AssertionError("Cortex mode must not load local MCP tools")

        deps = Deps(llm=lambda tier: None, tools=no_local_tools, store=store, cortex=cortex)
        graph = build_graph(deps).compile(checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": "c1"}, "recursion_limit": 200}
        await graph.ainvoke({"session_id": "c1", "request": "Add a field Foo__c"}, cfg)

        async def answer(text):
            snap = await graph.aget_state(cfg)
            payload = next(i.value for t in snap.tasks for i in t.interrupts)
            for g in store.gates:
                if g["id"] == payload["gate_id"]:
                    g["answer"], g["answered_by"] = text, "t@lilly.com"
            await graph.ainvoke(
                Command(resume={"text": text, "answered_by": "t@lilly.com", "gate_id": payload["gate_id"], "source": "api"}), cfg
            )

        for text in ["yes", "Y", "y", "y", "y", "m", "y", "s"]:
            await answer(text)

        snap = await graph.aget_state(cfg)
        open_gate = [i.value["name"] for t in snap.tasks for i in t.interrupts]
        self.assertEqual(store.status["c1"], "complete", f"open gate: {open_gate}")
        called = [a for a, _, _ in cortex.calls]
        self.assertEqual(called[0], AGENTS["design"].agent_id)
        self.assertIn(AGENTS["devops"].agent_id, called)
        self.assertTrue(all(sid.startswith("c1:") for _, _, sid in cortex.calls))
        design_q = cortex.calls[0][1]
        self.assertIn("Add a field Foo__c", design_q)
        self.assertIn("SESSION CONTEXT", design_q)
