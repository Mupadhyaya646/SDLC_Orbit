"""Tests for sdlc_orbit.gates (pure logic, stdlib only).

Run:  python -m unittest discover -s tests -v
"""
import importlib.util
import pathlib
import unittest

# Load gates.py directly so these tests need neither the package's third-party
# dependencies nor an installed distribution.
_spec = importlib.util.spec_from_file_location(
    "gates", pathlib.Path(__file__).resolve().parent.parent / "sdlc_orbit" / "gates.py"
)
gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gates)


class LooksLikeGate(unittest.TestCase):
    def test_bracket_options(self):
        self.assertTrue(gates.looks_like_gate("Deploy?\n[A] Deploy ALL\n[P] PARTIAL\n[C] CANCEL"))
        self.assertTrue(gates.looks_like_gate("[1] Local  [2] Confluence"))

    def test_design_confirmation(self):
        self.assertTrue(gates.looks_like_gate("Proceed with this plan? (yes / no / changes)"))
        self.assertTrue(gates.looks_like_gate("Proceed? ( YES/NO/CHANGES )"))

    def test_plain_text_is_not_a_gate(self):
        self.assertFalse(gates.looks_like_gate("Deployment complete. 5/5 components."))
        self.assertFalse(gates.looks_like_gate(""))
        self.assertFalse(gates.looks_like_gate(None))

    def test_long_bracket_token_is_not_an_option(self):
        self.assertFalse(gates.looks_like_gate("see [Salesforce docs] for details"))


class Choice(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(gates.choice("[F] fix"), "f")
        self.assertEqual(gates.choice("  S. skip"), "s")
        self.assertEqual(gates.choice("c"), "c")
        self.assertEqual(gates.choice(""), "")
        self.assertEqual(gates.choice(None), "")
        self.assertEqual(gates.choice("---"), "")


class DesignReply(unittest.TestCase):
    def test_yes_no_changes(self):
        self.assertEqual(gates.parse_design_reply("yes"), "yes")
        self.assertEqual(gates.parse_design_reply("Y"), "yes")
        self.assertEqual(gates.parse_design_reply("no"), "no")
        self.assertEqual(gates.parse_design_reply("No thanks"), "no")
        self.assertEqual(gates.parse_design_reply("changes: add a field"), "changes")
        self.assertEqual(gates.parse_design_reply("nothing to change, go ahead"), "changes")
        self.assertEqual(gates.parse_design_reply("yes."), "yes")


class PromptBlocks(unittest.TestCase):
    PLAN = (
        "\U0001F4DD ADMIN PROMPT:\n\"\"\"\nCreate Foo__c\n\"\"\"\n\n"
        "\U0001F4DD DEV PROMPT:\n\"\"\"\nNone\n\"\"\"\n"
    )

    def test_extract(self):
        admin, dev = gates.parse_design_plan(self.PLAN)
        self.assertEqual(admin, "Create Foo__c")
        self.assertIsNone(dev)

    def test_missing_blocks(self):
        self.assertEqual(gates.parse_design_plan("just prose"), (None, None))

    def test_na_is_empty(self):
        self.assertIsNone(gates.extract_prompt_block('ADMIN PROMPT:\n"""\nN/A\n"""', "ADMIN"))


class Verdict(unittest.TestCase):
    def test_verdict_lines(self):
        self.assertEqual(gates.parse_code_review_verdict("## VERDICT: \u2705 APPROVED"), gates.VERDICT_APPROVED)
        self.assertEqual(
            gates.parse_code_review_verdict("## Verdict: APPROVED WITH WARNINGS\n- minor"),
            gates.VERDICT_WARNINGS,
        )
        self.assertEqual(
            gates.parse_code_review_verdict("## VERDICT: \u274c CHANGES REQUIRED\n1. SOQL in loop"),
            gates.VERDICT_CHANGES,
        )

    def test_echoed_legend_is_skipped(self):
        text = (
            "## Verdict: APPROVED / APPROVED WITH WARNINGS / CHANGES REQUIRED\n"
            "Final: CHANGES REQUIRED because of SOQL in loop"
        )
        # Legend line names several verdicts -> skipped; whole-text fallback is fail-safe.
        self.assertEqual(gates.parse_code_review_verdict(text), gates.VERDICT_CHANGES)

    def test_not_applicable_is_unknown(self):
        self.assertEqual(
            gates.parse_code_review_verdict("NOT APPLICABLE \u2014 NOTHING TO REVIEW"), gates.VERDICT_UNKNOWN
        )

    def test_prose_approved_without_verdict_word_is_unknown(self):
        self.assertEqual(gates.parse_code_review_verdict("The design was approved earlier."), gates.VERDICT_UNKNOWN)

    def test_passes(self):
        self.assertTrue(gates.verdict_passes(gates.VERDICT_APPROVED))
        self.assertTrue(gates.verdict_passes(gates.VERDICT_WARNINGS))
        self.assertFalse(gates.verdict_passes(gates.VERDICT_CHANGES))
        self.assertFalse(gates.verdict_passes(gates.VERDICT_UNKNOWN))  # fail closed


class DocsPrompt(unittest.TestCase):
    def test_local(self):
        out = gates.build_docs_prompt({"docs_destination": "l", "docs_local_format": "docx"})
        self.assertIn("Local file. Format: docx", out)

    def test_confluence_new_and_existing(self):
        new = gates.build_docs_prompt(
            {"docs_destination": "c", "docs_confluence_new": True, "docs_confluence_location": "LSC/Design"}
        )
        self.assertIn("new page. Location/module: LSC/Design", new)
        existing = gates.build_docs_prompt(
            {"docs_destination": "c", "docs_confluence_new": False, "docs_confluence_location": "Page X"}
        )
        self.assertIn("update existing page at: Page X", existing)


class ProdPreflight(unittest.TestCase):
    @staticmethod
    def _gate(name, answer="C", by="a@lilly.com"):
        return {"gate_name": name, "answer": answer, "answered_by": by}

    def _all(self):
        return [self._gate(n) for n in gates.REQUIRED_PROD_GATES]

    def test_clear(self):
        self.assertEqual(gates.prod_preflight_problems(self._all(), uat_valid=True), [])

    def test_missing_gate(self):
        g = [x for x in self._all() if x["gate_name"] != "uat_approval"]
        problems = gates.prod_preflight_problems(g, uat_valid=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("uat_approval", problems[0])

    def test_open_gate_and_missing_identity(self):
        g = self._all()
        g[0]["answer"] = None
        g[1]["answered_by"] = ""
        problems = gates.prod_preflight_problems(g, uat_valid=True)
        self.assertEqual(len(problems), 2)

    def test_latest_row_wins(self):
        g = self._all() + [self._gate("qa_confirm", answer=None, by=None)]
        problems = gates.prod_preflight_problems(g, uat_valid=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("qa_confirm", problems[0])

    def test_stale_uat(self):
        problems = gates.prod_preflight_problems(self._all(), uat_valid=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("after UAT", problems[0])


class QuestionHeuristics(unittest.TestCase):
    def test_clarifying_question(self):
        self.assertTrue(gates.ends_with_question("Which queue should Web Form enrollments route to?"))
        self.assertTrue(gates.ends_with_question("Long preamble. " * 40 + "Is the field a picklist or text?\n"))
        self.assertFalse(gates.ends_with_question("Plan complete."))
        self.assertFalse(gates.ends_with_question(""))

    def test_has_yes_no_changes(self):
        self.assertTrue(gates.has_yes_no_changes("Proceed with this plan? (yes / no / changes)"))
        self.assertFalse(gates.has_yes_no_changes("Proceed? [Y] [N]"))


class CommitStatus(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(gates.parse_commit_status("# GitHub Deployment Memory\n## Commit\nStatus: SUCCESS\nBranch: x"), "success")
        self.assertEqual(gates.parse_commit_status("## Commit\nStatus: CANCELLED\n"), "cancelled")
        self.assertEqual(gates.parse_commit_status("## Commit\nStatus: FAILED\n"), "failed")

    def test_unfilled_legend_and_missing(self):
        self.assertEqual(gates.parse_commit_status("## Commit\nStatus: SUCCESS / FAILED / CANCELLED\n"), "unknown")
        self.assertEqual(gates.parse_commit_status("all done, pushed"), "unknown")


class DeployStatus(unittest.TestCase):
    def test_explicit_status_lines(self):
        self.assertEqual(gates.parse_deploy_status("Status: \u2705 SUCCESS\nOrg: QA"), "success")
        self.assertEqual(gates.parse_deploy_status("Status: \u274c FAILED\nOrg: QA"), "failed")
        self.assertEqual(gates.parse_deploy_status("## Deployment\nStatus: SUCCESS\n"), "success")

    def test_blocked_and_cancelled(self):
        self.assertEqual(gates.parse_deploy_status("\u274c DEPLOYMENT BLOCKED [abc]\nCode review verdict: CHANGES REQUIRED"), "blocked")
        self.assertEqual(gates.parse_deploy_status("Understood - deployment cancelled at your request."), "cancelled")

    def test_explicit_status_beats_stray_words(self):
        self.assertEqual(gates.parse_deploy_status("Status: SUCCESS\nNo components were cancelled."), "success")

    def test_unknown_and_legend(self):
        self.assertEqual(gates.parse_deploy_status("Deployed 5 components."), "unknown")
        self.assertEqual(gates.parse_deploy_status("Status: SUCCESS / FAILED"), "unknown")


if __name__ == "__main__":
    unittest.main()
