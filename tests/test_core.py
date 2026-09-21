"""Synthetic contract fixtures only. These are NOT saved provider runs."""
import copy
import json
import unittest
from unittest.mock import patch

import core


FIXTURES = {
    "Linkup": {"results": [{"name": "Fixture", "url": "https://example.com", "content": "Evidence L"}]},
    "Exa": {"results": [{"title": "Fixture", "url": "https://example.com", "highlights": ["Evidence E", "Second passage"], "publishedDate": "2026-09-01"}], "costDollars": {"total": 0.01}},
    "Parallel": {"results": [{"title": "Fixture", "url": "https://example.com", "excerpts": ["Evidence P"], "publish_date": "2026-09-01"}]},
    "Tavily": {"results": [{"title": "Fixture", "url": "https://example.com", "content": "Evidence T"}], "usage": {"credits": 1}},
    "Brave": {"web": {"results": [{"title": "Fixture", "url": "https://example.com", "description": "Evidence B", "extra_snippets": ["Extra B"]}]}},
}

BRIEF_TEXT = "\n".join(
    [f"## {h}\n" + ("Fact [Q1-S1]" if h == "Company" else "Hello there") for h in core.BRIEF_HEADINGS])
DEEP_DIVE_TEXT = "\n".join(f"## {h}\nNotes [Q1-S1]" for h in core.DEEP_DIVE_HEADINGS)


def transport(method, url, payload, headers):
    p = next(p for p in core.PROVIDERS if p.lower() in url)
    return {"status_code": 200, "raw_text": json.dumps(FIXTURES[p]), "error": None, "seconds": .01,
            "timestamp": "2026-09-21T00:00:00Z", "response_headers": {}}


def fixture_run(company="Dust", domain="dust.tt"):
    return core.research(company, domain, "2026-06-23", "2026-09-21", list(core.PROVIDERS),
                         dict.fromkeys(core.PROVIDERS, "fixture-key"), transport=transport)


def generated_document(verdict="plausible", brief=BRIEF_TEXT):
    return {
        "fit_assessment": {
            "verdict": verdict, "rationale": "Fixture rationale.",
            "icp_signals_present": [{"signal": "Documented web search feature", "source_id": "Q1-S1"}],
            "disqualifying_signals": [],
            "entity_confirmed": True, "entity_note": "",
            "confidence": "medium", "evidence_gaps": "Volume unknown.",
        },
        "evidence_summary": {q: {"finding": "Fixture finding only", "source_id": f"{q}-S1",
                                 "excerpt": "Evidence L", "uncertainty": "Needs qualification"}
                             for q in core.SUMMARY_LABELS},
        "brief_markdown": brief,
        "deep_dive_markdown": DEEP_DIVE_TEXT,
    }


def llm_transport(document=None, captured=None):
    def send(method, url, payload, headers):
        if captured is not None:
            captured.append(payload)
        body = {"status": "completed", "usage": {"input_tokens": 1000, "output_tokens": 500},
                "output": [{"type": "message", "content": [{"type": "output_text",
                                                            "text": json.dumps(document or generated_document())}]}]}
        return {"error": None, "seconds": 1, "raw_text": json.dumps(body), "status_code": 200}
    return send


class IdentityTests(unittest.TestCase):
    def test_domain_normalisation_accepts_what_people_paste(self):
        for raw in ["Example.com", "https://www.example.com/pricing?x=1", "www.example.com", " example.com "]:
            self.assertEqual(core.normalise_domain(raw), "example.com")
        self.assertEqual(core.normalise_domain("https://sub.example.co.uk/a/b"), "sub.example.co.uk")

    def test_domain_normalisation_rejects_rubbish(self):
        for raw in ["", "   ", "not a domain", "localhost", "example", "http://", "a b.com", "x" * 300 + ".com"]:
            with self.assertRaises(ValueError, msg=raw):
                core.normalise_domain(raw)

    def test_company_name_validation(self):
        self.assertEqual(core.normalise_company_name("  Acme   Analytics "), "Acme Analytics")
        for raw in ["", "   ", "---", "x" * 200]:
            with self.assertRaises(ValueError, msg=raw):
                core.normalise_company_name(raw)

    def test_any_company_can_be_researched(self):
        run = fixture_run("Acme Analytics", "https://www.acme.com/")
        self.assertEqual((run["company"], run["domain"]), ("Acme Analytics", "acme.com"))
        self.assertFalse(run["featured"])
        for q in run["questions"]:
            self.assertIn("acme.com", q["query"])
        self.assertTrue(fixture_run()["featured"])

    def test_bad_identity_makes_no_requests(self):
        for company, domain in [("", "dust.tt"), ("Dust", "not a domain")]:
            with self.assertRaises(ValueError):
                core.research(company, domain, "2026-06-23", "2026-09-21", ["Linkup"], {"Linkup": "k"},
                              transport=lambda *a: self.fail("Invalid identity must not call APIs"))


class ContextTests(unittest.TestCase):
    def test_context_is_frozen_into_the_prompt_and_the_run(self):
        from linkup_context import CONTEXT_SHA256, CONTEXT_JSON
        self.assertIn(CONTEXT_JSON, core.INSTRUCTIONS)
        run = fixture_run()
        self.assertEqual(run["context_sha256"], CONTEXT_SHA256)
        self.assertTrue(run["context_version"])

    def test_every_provider_receives_identical_context(self):
        run = fixture_run()
        captured = []
        for provider in core.PROVIDERS:
            core.generate_brief(run, provider, "key", llm_transport(captured=captured))
        instructions = {payload["instructions"] for payload in captured}
        self.assertEqual(len(instructions), 1, "Context must be byte-identical across providers")

    def test_context_describes_the_vendor_not_the_prospect(self):
        from linkup_context import LINKUP_CONTEXT
        self.assertEqual(LINKUP_CONTEXT["entity"]["domain"], "linkup.so")
        self.assertTrue(LINKUP_CONTEXT["usage_rules"])
        self.assertTrue(LINKUP_CONTEXT["icp"]["anti_signals"])
        for verdict in core.FIT_VERDICTS:
            self.assertIn(verdict, LINKUP_CONTEXT["icp"]["verdict_guidance"])


class RetrievalTests(unittest.TestCase):
    def test_all_providers_and_identical_questions(self):
        run = fixture_run()
        self.assertEqual(sum(len(v["records"]) for v in run["providers"].values()), 15)
        for p, entry in run["providers"].items():
            for record in entry["records"]:
                self.assertIsNone(record["error"])
                self.assertTrue(record["evidence"][0]["text"])
                request = record["request"]
                field = "objective" if p == "Parallel" else "q" if p in ("Linkup", "Brave") else "query"
                self.assertEqual(request[field], record["question"]["query"])

    def test_linkup_depth_is_recorded_and_applied(self):
        run = fixture_run()
        self.assertEqual(run["linkup_depth"], core.LINKUP_DEPTH)
        _, _, request = core.request_spec("Linkup", run["questions"][0])
        self.assertEqual(request["depth"], core.LINKUP_DEPTH)

    def test_query_lengths_for_search_baseline(self):
        for name, domain in core.FEATURED_COMPANIES.items():
            for q in core.questions(name, domain, "2026-06-23", "2026-09-21"):
                self.assertLessEqual(len(q["query"]), 400)
                self.assertLessEqual(len(q["query"].split()), 50)

    def test_selected_dates_reach_only_q2_without_domain_restrictions(self):
        # Two unrelated windows prove dates are supplied by the caller, not fixed.
        for start, end in [("2026-03-25", "2026-09-21"), ("2025-01-07", "2025-02-14")]:
            qs = core.questions("Dust", "dust.tt", start, end)
            for provider in core.PROVIDERS:
                for q in qs:
                    _, _, request = core.request_spec(provider, q)
                    serialized = json.dumps(request)
                    for restriction in ("includeDomains", "excludeDomains", "include_domains", "exclude_domains", "site:"):
                        self.assertNotIn(restriction, serialized)
                    if q["id"] != "Q2":
                        for field in ("fromDate", "toDate", "startPublishedDate", "endPublishedDate", "after_date", "start_date", "end_date", "freshness"):
                            self.assertNotIn(field, serialized)
                        continue
                    self.assertIn(start, q["query"])
                    self.assertIn(end, q["query"])
                    if provider == "Linkup":
                        self.assertEqual((request["fromDate"], request["toDate"]), (start, end))
                    elif provider == "Exa":
                        self.assertEqual(request["startPublishedDate"], start + "T00:00:00.000Z")
                        self.assertEqual(request["endPublishedDate"], end + "T23:59:59.999Z")
                    elif provider == "Parallel":
                        self.assertEqual(request["advanced_settings"]["source_policy"], {"after_date": start})
                    elif provider == "Tavily":
                        self.assertEqual((request["start_date"], request["end_date"]), (start, end))
                        self.assertTrue(request["filter_by_published_date"])
                    else:
                        self.assertEqual(request["freshness"], start + "to" + end)

    def test_invalid_windows_make_no_requests(self):
        for start, end in [("2026-09-21", "2026-09-21"), ("2026-09-22", "2026-09-21")]:
            with self.assertRaises(ValueError):
                core.research("Dust", "dust.tt", start, end, ["Linkup"], {"Linkup": "key"},
                              transport=lambda *args: self.fail("Invalid window must not call APIs"))

    def test_raw_preservation_and_errors(self):
        raw = ' {"results": []} \n'
        def fail(*args):
            return {"error": "HTTP 429", "status_code": 429, "raw_text": raw, "seconds": 1}
        record = core.retrieve("Linkup", core.questions("Dust", "dust.tt", "a", "b")[0], "key", fail)
        self.assertEqual(record["raw_text"], raw)
        self.assertEqual(record["error"], "HTTP 429")
        self.assertEqual(record["evidence"], [])

    def test_truncation_does_not_change_raw_evidence(self):
        records = fixture_run()["providers"]["Exa"]["records"]
        records[0]["evidence"][0]["text"] = '"界\\' * 20000
        original = copy.deepcopy(records)
        groups, stats = core.evidence_bundle(records, budget=1000)
        self.assertEqual(records, original)
        self.assertTrue(stats[0]["truncated"])
        self.assertLessEqual(stats[0]["serialized_evidence_chars"], 1000)
        self.assertEqual(groups[0]["sources"][0]["url"], "https://example.com")

    def test_preview_does_not_shorten_llm_evidence(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        records[0]["evidence"][0]["text"] = "Original passage " * 100
        before, _ = core.evidence_bundle(records)
        preview = core.passage_preview(records[0]["evidence"][0]["text"])
        after, _ = core.evidence_bundle(records)
        self.assertLessEqual(len(preview), 321)
        self.assertEqual(before, after)
        self.assertGreater(len(after[0]["sources"][0]["text"]), 320)


class GenerationTests(unittest.TestCase):
    def test_no_cross_provider_evidence(self):
        run = fixture_run()
        with self.assertRaises(ValueError):
            core.evidence_bundle([run["providers"]["Linkup"]["records"][0], run["providers"]["Exa"]["records"][0]])
        captured = []
        result = core.generate_brief(run, "Linkup", "key", llm_transport(captured=captured))
        self.assertIsNone(result["error"])
        self.assertIn("Evidence L", captured[0]["input"])
        self.assertNotIn("Evidence E", captured[0]["input"])
        self.assertNotIn("tools", captured[0])
        self.assertFalse(captured[0]["store"])
        self.assertEqual(captured[0]["model"], core.MODEL)
        self.assertEqual(captured[0]["max_output_tokens"], core.MAX_OUTPUT_TOKENS)
        self.assertEqual(len(captured), 1)
        self.assertEqual(len(result["evidence_summary"]), 3)
        self.assertTrue(all(r["excerpt_matches_source"] for r in result["evidence_summary"]))
        self.assertEqual(result["fit"]["verdict"], "plausible")
        self.assertTrue(result["deep_dive"])
        self.assertEqual(result["checks"], [])

    def test_summary_flags_bad_citations_and_excerpts(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document()
        doc["evidence_summary"]["Q1"]["source_id"] = "Q1-S99"
        doc["evidence_summary"]["Q2"]["excerpt"] = "Invented excerpt"
        _, _, _, rows, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertEqual(rows[0]["source_url"], "")
        self.assertFalse(rows[1]["excerpt_matches_source"])
        self.assertTrue(any("unknown source" in c for c in checks))
        self.assertTrue(any("does not exactly match" in c for c in checks))

    def test_fit_verdict_citations_are_checked(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document()
        doc["fit_assessment"]["icp_signals_present"] = [{"signal": "Invented", "source_id": "Q9-S9"}]
        _, _, _, _, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertTrue(any("unknown source ID" in c for c in checks))

    def test_claimed_fit_without_signals_is_flagged(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document(verdict="strong")
        doc["fit_assessment"]["icp_signals_present"] = []
        _, _, _, _, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertTrue(any("lists no ICP signals" in c for c in checks))

    def test_not_a_fit_without_a_disqualifying_signal_is_flagged(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document(verdict="not_a_fit")
        doc["fit_assessment"]["disqualifying_signals"] = []
        _, _, _, _, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertTrue(any("no disqualifying signal is cited" in c for c in checks))

    def test_competitor_test_rationale_is_flagged(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        for rationale in ["Unify does not provide a web search or retrieval API over external web data.",
                          "It is not a web retrieval platform.",
                          "The company does not sell search infrastructure as Linkup does."]:
            doc = generated_document(verdict="not_a_fit")
            doc["fit_assessment"]["rationale"] = rationale
            _, _, _, _, checks = core.parse_generated_output(json.dumps(doc), bundle)
            self.assertTrue(any("competitor test" in c for c in checks), rationale)

    def test_excerpt_match_survives_whitespace_normalisation(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        records[0]["evidence"][0]["text"] = "Build targeted lists\nfrom 40+ data vendors\n\nand sequence them."
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document()
        doc["evidence_summary"]["Q1"]["excerpt"] = "Build targeted lists from 40+ data vendors"
        _, _, _, rows, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertTrue(rows[0]["excerpt_matches_source"])
        self.assertFalse(any("does not exactly match" in c for c in checks))

    def test_invented_excerpt_is_still_caught(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document()
        doc["evidence_summary"]["Q1"]["excerpt"] = "Unify uses Linkup in production today"
        _, _, _, rows, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertFalse(rows[0]["excerpt_matches_source"])
        self.assertTrue(any("does not exactly match" in c for c in checks))

    def test_icp_encodes_the_buyer_test(self):
        from linkup_context import LINKUP_CONTEXT
        icp = LINKUP_CONTEXT["icp"]
        self.assertTrue(icp["how_to_apply"])
        self.assertTrue(icp["not_anti_signals"])
        # The published customers whose product shape the old ICP wrongly rejected.
        named = json.dumps(icp["worked_patterns"])
        self.assertIn("Artisan", named)
        self.assertIn("Pennylane", named)

    def test_wrong_entity_is_surfaced(self):
        records = fixture_run()["providers"]["Linkup"]["records"]
        bundle, _ = core.evidence_bundle(records)
        doc = generated_document()
        doc["fit_assessment"]["entity_confirmed"] = False
        doc["fit_assessment"]["entity_note"] = "Evidence describes a different Dust."
        fit, _, _, _, checks = core.parse_generated_output(json.dumps(doc), bundle)
        self.assertFalse(fit["entity_confirmed"])
        self.assertTrue(any("WRONG ENTITY RISK" in c for c in checks))

    def test_not_a_fit_suppresses_the_email(self):
        run = fixture_run()
        brief = BRIEF_TEXT.replace("## First-touch email\nHello there",
                                   "## First-touch email\nNo outreach recommended. No documented use of external web data.")
        doc = generated_document(verdict="not_a_fit", brief=brief)
        doc["fit_assessment"]["icp_signals_present"] = []
        doc["fit_assessment"]["disqualifying_signals"] = [{"signal": "No external web data", "source_id": "Q1-S1"}]
        result = core.generate_brief(run, "Linkup", "key", llm_transport(doc))
        self.assertEqual(result["fit"]["verdict"], "not_a_fit")
        self.assertTrue(result["email_suppressed"])
        self.assertEqual(result["checks"], [])

    def test_email_drafted_despite_no_fit_is_flagged(self):
        run = fixture_run()
        result = core.generate_brief(run, "Linkup", "key", llm_transport(generated_document(verdict="not_a_fit")))
        self.assertTrue(any("Do not send it" in c for c in result["checks"]))

    def test_missing_headings_are_flagged(self):
        run = fixture_run()
        doc = generated_document(brief="## Company\nOnly one heading [Q1-S1]\n## First-touch email\nHi")
        result = core.generate_brief(run, "Linkup", "key", llm_transport(doc))
        self.assertTrue(any("missing expected sections" in c for c in result["checks"]))

    def test_vendor_context_cited_as_prospect_evidence_is_flagged(self):
        run = fixture_run()
        doc = generated_document(brief=BRIEF_TEXT.replace("Fact [Q1-S1]", "Fact [Q1-S1] and [CTX-01]"))
        result = core.generate_brief(run, "Linkup", "key", llm_transport(doc))
        self.assertTrue(any("vendor context" in c for c in result["checks"]))

    def test_truncated_response_is_reported_as_truncation(self):
        run = fixture_run()
        def truncated(method, url, payload, headers):
            body = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
            return {"error": None, "seconds": 1, "raw_text": json.dumps(body), "status_code": 200}
        result = core.generate_brief(run, "Linkup", "key", truncated)
        self.assertIn("max_output_tokens", result["error"])
        self.assertIn("MAX_OUTPUT_TOKENS", result["error"])

    def test_failed_retrieval_does_not_invent_brief(self):
        run = fixture_run()
        for record in run["providers"]["Linkup"]["records"]:
            record["error"] = "HTTP 401"
        def forbidden(*args):
            self.fail("Must not call LLM with no evidence")
        result = core.generate_brief(run, "Linkup", "key", forbidden)
        self.assertIn("skipped", result["error"])


class CostTests(unittest.TestCase):
    """These test the cost ARITHMETIC, so they pin their own price table.

    They must not depend on what SEARCH_COST_ESTIMATE_USD happens to contain in core.py:
    filling in your real provider prices is expected, and doing so must never break the suite.
    test_price_table_is_well_formed below is the one that checks your actual configuration."""

    PRICES = {"Linkup": 0.006, "Exa": None, "Parallel": None, "Tavily": None, "Brave": 0.005}
    LLM_PRICES = {"input": 0.40, "output": 1.60}

    def setUp(self):
        for target, values in ((core.SEARCH_COST_ESTIMATE_USD, self.PRICES),
                               (core.LLM_COST_PER_MTOK_USD, self.LLM_PRICES)):
            patcher = patch.dict(target, values, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unconfigured_price_is_not_reported_as_free(self):
        usd, basis = core.record_cost({"provider": "Parallel"})
        self.assertIsNone(usd)
        self.assertEqual(basis, "not configured")

    def test_provider_reported_cost_beats_the_estimate(self):
        usd, basis = core.record_cost({"provider": "Linkup", "provider_cost_estimate": 0.02})
        self.assertEqual((usd, basis), (0.02, "provider-reported"))

    def test_partial_pricing_is_flagged_incomplete(self):
        run = fixture_run()
        run["providers"]["Parallel"]["brief"] = {"usage": {"input_tokens": 1000, "output_tokens": 500}}
        cost = core.provider_cost(run["providers"]["Parallel"])
        self.assertFalse(cost["complete"])
        self.assertEqual(cost["unpriced_requests"], 3)
        self.assertIsNone(cost["total_usd"])

    def test_complete_pricing_totals_search_plus_llm(self):
        run = fixture_run()
        run["providers"]["Linkup"]["brief"] = {"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
        cost = core.provider_cost(run["providers"]["Linkup"])
        self.assertTrue(cost["complete"])
        self.assertAlmostEqual(cost["search_usd"], 3 * self.PRICES["Linkup"], places=5)
        self.assertAlmostEqual(cost["llm_usd"], 0.40 + 1.60, places=5)


class PriceConfigTests(unittest.TestCase):
    """Checks the real table in core.py without caring which prices you filled in."""

    def test_price_table_is_well_formed(self):
        self.assertEqual(set(core.SEARCH_COST_ESTIMATE_USD), set(core.PROVIDERS))
        for provider, price in core.SEARCH_COST_ESTIMATE_USD.items():
            if price is None:
                continue
            self.assertIsInstance(price, (int, float), provider)
            self.assertFalse(isinstance(price, bool), provider)
            self.assertGreater(price, 0, f"{provider}: use None for unknown, never 0, which reads as free")
            self.assertLess(price, 1, f"{provider}: this is the price of ONE request, in dollars")
        for key in ("input", "output"):
            self.assertGreater(core.LLM_COST_PER_MTOK_USD[key], 0)


class SavedRunTests(unittest.TestCase):
    def test_export_excludes_brave_and_derived_brief(self):
        run = fixture_run()
        run["providers"]["Brave"]["brief"] = {"text": "PRIVATE BRAVE MARKER"}
        exported = core.export_run(run, ["Linkup", "Exa", "Tavily", "Parallel"])
        self.assertNotIn("PRIVATE BRAVE MARKER", json.dumps(exported))
        self.assertIn("Brave", run["providers"])
        loaded = core.load_saved(json.dumps(exported))
        self.assertEqual(loaded["origin"], "saved")

    def test_saved_runs_are_not_restricted_to_featured_companies(self):
        exported = core.export_run(fixture_run("Acme Analytics", "acme.com"), list(core.PROVIDERS))
        loaded = core.load_saved(json.dumps(exported))
        self.assertEqual(loaded["company"], "Acme Analytics")

    def test_malformed_exports_are_rejected(self):
        good = core.export_run(fixture_run(), list(core.PROVIDERS))
        for mutate in (
            lambda d: d.update(schema_version="99"),
            lambda d: d.update(company=""),
            lambda d: d.pop("domain"),
            lambda d: d.update(providers={}),
            lambda d: d.update(providers={"NotAProvider": {"records": []}}),
            lambda d: d["providers"]["Linkup"].update(records=[]),
        ):
            broken = copy.deepcopy(good)
            mutate(broken)
            with self.assertRaises(ValueError):
                core.load_saved(json.dumps(broken))


    def test_run_summary_carries_verdicts(self):
        run = fixture_run()
        run["providers"]["Linkup"]["brief"] = {"fit": {"verdict": "weak"}}
        summary = core.run_summary(run)
        self.assertEqual(summary["verdicts"]["Linkup"], "weak")
        self.assertEqual(summary["verdicts"]["Exa"], "no brief")

    def test_credentials_are_never_in_export(self):
        run = fixture_run()
        self.assertNotIn("fixture-key", json.dumps(core.export_run(run, core.PROVIDERS)))
        self.assertFalse(core.safe_url("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()
