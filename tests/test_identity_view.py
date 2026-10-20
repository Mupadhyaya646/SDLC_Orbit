"""Tests for identity stamping and dashboard view derivation (stdlib only)."""
import base64
import datetime as dt
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdlc_orbit.api import view  # noqa: E402
from sdlc_orbit.api.identity import IdentityError, identity_from_headers, resolve_identity  # noqa: E402
from sdlc_orbit.state import STAGE_NAMES, stage_for_step  # noqa: E402


def _jwt(claims: dict) -> str:
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode()  # noqa: E731
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


class Identity(unittest.TestCase):
    def test_alb_oidc_jwt(self):
        h = {"X-Amzn-Oidc-Data": _jwt({"email": "mayank.upadhyaya@lilly.com"})}
        self.assertEqual(identity_from_headers(h), "mayank.upadhyaya@lilly.com")

    def test_plain_header_and_case_insensitivity(self):
        self.assertEqual(identity_from_headers({"X-Forwarded-Email": "a@lilly.com"}), "a@lilly.com")

    def test_configured_header_wins(self):
        h = {"x-forwarded-email": "wrong@lilly.com", "x-my-user": "right@lilly.com"}
        self.assertEqual(identity_from_headers(h, "X-My-User"), "right@lilly.com")

    def test_malformed_jwt_is_not_an_error(self):
        self.assertIsNone(identity_from_headers({"x-amzn-oidc-data": "garbage"}))

    def test_body_never_overrides_a_verified_header(self):
        who = resolve_identity({"x-forwarded-email": "real@lilly.com"}, "you")
        self.assertEqual(who, "real@lilly.com")

    def test_unverified_fallback_is_marked(self):
        self.assertEqual(resolve_identity({}, "you"), "unverified:you")
        self.assertEqual(resolve_identity({}, None), "unverified:unknown")

    def test_strict_mode_fails_closed(self):
        with self.assertRaises(IdentityError):
            resolve_identity({}, "you", strict=True)

    def test_dev_mode(self):
        self.assertEqual(resolve_identity({}, "me", mode="dev"), "me")
        self.assertEqual(resolve_identity({}, None, mode="dev"), "dev-user")


class Stages(unittest.TestCase):
    def test_seven_stages(self):
        self.assertEqual(len(STAGE_NAMES), 7)
        self.assertEqual(set(range(7)), {stage_for_step(s) for s in (
            "design", "build", "test", "review", "commit", "qa_deploy", "prod_deploy")})

    def test_every_release_step_is_stage_6(self):
        for s in ("pr_approval", "merge", "prod_preflight", "prod_deploy", "prod_confirm", "docs_preflight", "docs", "complete"):
            self.assertEqual(stage_for_step(s), 6, s)

    def test_qa_steps_are_stage_5(self):
        for s in ("qa_deploy", "qa_confirm", "uat"):
            self.assertEqual(stage_for_step(s), 5, s)

    def test_unknown_step_defaults_to_design(self):
        self.assertEqual(stage_for_step(None), 0)
        self.assertEqual(stage_for_step("nope"), 0)


class StatusDerivation(unittest.TestCase):
    def test_awaiting_marks_current_stage(self):
        state = {"step": "review", "active_agents": ["salesforce-code-review-agent"]}
        st = view.stage_statuses("awaiting_input", state)
        self.assertEqual(st[:3], ["done"] * 3)
        self.assertEqual(st[3], "awaiting")
        self.assertEqual(st[4:], ["idle"] * 3)

    def test_error_marks_failed(self):
        self.assertEqual(view.stage_statuses("error", {"step": "commit"})[4], "failed")

    def test_complete_is_all_done(self):
        self.assertEqual(view.stage_statuses("complete", {"step": "complete"}), ["done"] * 7)

    def test_abort_marks_current_cancelled(self):
        self.assertEqual(view.stage_statuses("aborted", {"step": "uat"})[5], "cancelled")

    def test_agent_status(self):
        state = {"step": "design", "active_agents": ["salesforce-design-agent-d"]}
        s = view.agent_statuses("awaiting_input", state)
        self.assertEqual(s["salesforce-design-agent-d"], "awaiting")
        self.assertEqual(s["salesforce-admin-agent-d"], "idle")

    def test_devops_runs_in_two_stages(self):
        s = view.agent_statuses("in_progress", {"step": "prod_deploy", "active_agents": []})
        self.assertEqual(s["salesforce-devops-agent-d"], "running")
        self.assertEqual(s["github-commit-agent"], "done")

    def test_roster_ids_match_original_agents(self):
        ids = {a["id"] for a in view.AGENT_ROSTER}
        self.assertEqual(len(ids), 8)
        self.assertIn("github-commit-agent", ids)
        self.assertIn("salesforce-design-agent-d", ids)


class LogAndJournal(unittest.TestCase):
    T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)

    def test_log_merges_chronologically(self):
        turns = [{"created_at": self.T0 + dt.timedelta(seconds=5), "agent_name": "a", "content": "x" * 300}]
        gates = [{"id": 1, "answer": "Y", "answered_by": "u@lilly.com", "answered_at": self.T0, "agent_name": "a"}]
        rows = view.log_rows(turns, gates)
        self.assertEqual([r["kind"] for r in rows], ["decision", "turn"])
        self.assertEqual(len(rows[1]["summary"]), 200)
        self.assertIn("u@lilly.com", rows[0]["summary"])
        self.assertEqual([r["n"] for r in rows], [1, 2])

    def test_journal_orders_answered_before_pending(self):
        gates = [
            {"id": 1, "agent_name": "a", "gate_name": "g1", "question": "q1", "answer": None, "answered_by": None, "answered_at": None},
            {"id": 2, "agent_name": "a", "gate_name": "g2", "question": "q2", "answer": "Y", "answered_by": "u", "answered_at": self.T0},
        ]
        rows = view.journal_rows(gates)
        self.assertEqual([r["id"] for r in rows], ["D-02", "D-01"])
        self.assertEqual([r["pending"] for r in rows], [False, True])


if __name__ == "__main__":
    unittest.main()
