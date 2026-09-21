import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from test_core import fixture_run, generated_document
from core import evidence_bundle, parse_generated_output

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def unlocked_app():
    at = AppTest.from_file(APP)
    at.secrets["ALLOW_LIVE"] = True
    at.secrets["APP_PASSWORD"] = "test-password"
    at.secrets["OPENAI_API_KEY"] = "test-key"
    for key in ("LINKUP_API_KEY", "EXA_API_KEY", "PARALLEL_API_KEY", "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"):
        at.secrets[key] = "test-key"
    at.session_state["unlocked"] = True
    return at


def briefed_run():
    run = fixture_run()
    bundle, stats = evidence_bundle(run["providers"]["Linkup"]["records"])
    fit, brief, deep_dive, rows, checks = parse_generated_output(json.dumps(generated_document()), bundle)
    run["providers"]["Linkup"]["brief"] = {"fit": fit, "text": brief, "deep_dive": deep_dive,
                                           "evidence_summary": rows, "checks": checks, "stats": stats,
                                           "seconds": 1, "error": None,
                                           "usage": {"input_tokens": 1000, "output_tokens": 500}}
    return run


class AppTests(unittest.TestCase):
    def test_live_buttons_with_mocked_transport(self):
        at = unlocked_app()
        with patch("core.research", return_value=fixture_run()) as retrieve:
            at.run()
            self.assertEqual(at.date_input[0].value, date.today() - timedelta(days=180))
            at.date_input[0].set_value(date(2025, 1, 7))
            at.date_input[1].set_value(date(2025, 2, 14))
            next(b for b in at.button if b.label == "1. Research prospect").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(retrieve.call_count, 1)
            # research(company, domain, start, end, ...)
            self.assertEqual(retrieve.call_args.args[0:4], ("Unify", "unifygtm.com", "2025-01-07", "2025-02-14"))
        brief = {"error": None, "seconds": 1, "text": "## Company\nFixture only", "deep_dive": "",
                 "fit": None, "stats": [], "checks": [], "evidence_summary": []}
        with patch("core.generate_brief", return_value=brief) as generate:
            next(b for b in at.button if b.label.startswith("2. Generate")).click().run()
            self.assertFalse(at.exception)
            self.assertEqual(generate.call_count, 5)
            at.run()
            self.assertEqual(generate.call_count, 5)  # UI reruns must not spend again.

    def test_custom_company_fields_appear_and_are_used(self):
        at = unlocked_app()
        at.run()
        at.selectbox[0].set_value("Other company…").run()
        self.assertFalse(at.exception)
        labels = [t.label for t in at.text_input]
        self.assertIn("Company name", labels)
        self.assertIn("Official domain", labels)
        next(t for t in at.text_input if t.label == "Company name").set_value("Acme Analytics")
        next(t for t in at.text_input if t.label == "Official domain").set_value("https://www.acme.com/")
        with patch("core.research", return_value=fixture_run("Acme Analytics", "acme.com")) as retrieve:
            next(b for b in at.button if b.label == "1. Research prospect").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(retrieve.call_args.args[0:2], ("Acme Analytics", "acme.com"))

    def test_invalid_custom_identity_blocks_the_run(self):
        at = unlocked_app()
        at.run()
        at.selectbox[0].set_value("Other company…").run()
        next(t for t in at.text_input if t.label == "Company name").set_value("Acme")
        next(t for t in at.text_input if t.label == "Official domain").set_value("not a domain")
        with patch("core.research") as retrieve:
            next(b for b in at.button if b.label == "1. Research prospect").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(retrieve.call_count, 0)
            self.assertTrue(at.error)

    def test_empty_app_without_keys(self):
        at = AppTest.from_file(APP).run(timeout=30)
        self.assertFalse(at.exception)
        self.assertTrue(next(b for b in at.button if b.label == "1. Research prospect").disabled)

    def test_verdict_summary_and_deep_dive_render(self):
        at = AppTest.from_file(APP)
        at.session_state["run"] = briefed_run()
        at.run(timeout=30)
        self.assertFalse(at.exception)
        self.assertTrue(any(e.label == "Expand full passage" for e in at.expander))
        self.assertTrue(any(e.label == "Read the full prospect brief" for e in at.expander))
        self.assertTrue(any(e.label == "Deep dive: objections, stakeholders, first call" for e in at.expander))
        self.assertTrue(any(e.label == "Signals behind this verdict" for e in at.expander))
        stats = [m.value for m in at.markdown if 'class="stats"' in m.value]
        self.assertTrue(stats)
        self.assertTrue(any("Cost" in s for s in stats))
        table = next(m.value for m in at.markdown if '<table class="summary-table">' in m.value)
        self.assertEqual(table.count('<tr>'), 4)  # header plus exactly three rows
        self.assertIn('Q1-S1', table)
        self.assertTrue(any("Plausible fit" in m.value for m in at.markdown))
        self.assertEqual(len(at.tabs), 5)
        at.radio[0].set_value(2).run()
        self.assertFalse(at.exception)

    def test_back_button_returns_to_the_company_list(self):
        at = AppTest.from_file(APP)
        at.session_state["run"] = briefed_run()
        at.run(timeout=30)
        self.assertFalse(at.exception)
        next(b for b in at.button if b.label == "← All companies").click().run()
        self.assertFalse(at.exception)
        self.assertIsNone(at.session_state.get("run"))
        self.assertFalse(any(b.label == "← All companies" for b in at.button))

    def test_provider_disagreement_is_surfaced(self):
        at = AppTest.from_file(APP)
        run = briefed_run()
        run["providers"]["Exa"]["brief"] = {"fit": {"verdict": "not_a_fit"}, "text": "", "deep_dive": "",
                                            "evidence_summary": [], "checks": [], "stats": [], "seconds": 1,
                                            "error": None}
        at.session_state["run"] = run
        at.run(timeout=30)
        self.assertFalse(at.exception)
        self.assertTrue(any("providers disagree" in c.value.lower() for c in at.caption))


if __name__ == "__main__":
    unittest.main()
