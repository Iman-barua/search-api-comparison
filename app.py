from __future__ import annotations

import hmac
import json
import os
import re
from html import escape
from urllib.parse import urlsplit
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from core import (FEATURED_COMPANIES, PROVIDERS, KEY_NAMES, MODES, DOCS, MODEL, INSTRUCTIONS,
                  LINKUP_DEPTH, MAX_OUTPUT_TOKENS, COST_CHECKED_ON, FIT_VERDICTS,
                  questions, research, generate_brief, evidence_bundle, export_run, load_saved,
                  safe_url, passage_preview, normalise_domain, normalise_company_name,
                  provider_cost, run_summary)
from linkup_context import LINKUP_CONTEXT

st.set_page_config(page_title="Search to Signal | Prospect research", page_icon="🔎", layout="wide")
st.markdown("""<style>
.block-container {max-width:1480px; padding-top:6rem;}
h1 {letter-spacing:-0.04em; font-weight:750;}
.stats {display:flex;gap:8px;flex-wrap:wrap;margin:2px 0 12px;}
.stat {border:1px solid #80808038;border-radius:9px;padding:7px 12px;line-height:1.25;white-space:nowrap;}
.stat span {display:block;font-size:0.66rem;letter-spacing:0.05em;text-transform:uppercase;opacity:0.55;margin-bottom:3px;}
.stat b {font-weight:650;font-size:1.02rem;}
div[data-testid="stCaptionContainer"] {line-height:1.5;}
.summary-table {width:100%;border-collapse:collapse;font-size:0.88rem;table-layout:fixed;}
.summary-table th,.summary-table td {text-align:left;vertical-align:top;padding:10px 8px;border-bottom:1px solid #80808040;overflow-wrap:anywhere;}
.summary-table th {font-weight:650;}
.summary-table th:first-child {width:15%;}
.summary-table small {display:block;margin-top:7px;opacity:0.7;}
.brief-heading {font-weight:650;margin:12px 0 3px;}
.verdict {display:inline-block;padding:3px 10px;border-radius:999px;font-size:0.78rem;font-weight:650;letter-spacing:0.02em;}
.strip {display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 18px;}
.strip-card {flex:1 1 150px;border:1px solid #80808033;border-radius:12px;padding:12px 14px;}
.strip-card b {display:block;font-size:0.82rem;letter-spacing:0.04em;text-transform:uppercase;opacity:0.65;margin-bottom:7px;}
.strip-card small {display:block;margin-top:7px;opacity:0.6;font-size:0.76rem;}
.email-card {border:1px solid #80808033;border-left:3px solid #1e40af;border-radius:10px;padding:14px 16px;margin-top:6px;white-space:pre-wrap;font-size:0.92rem;line-height:1.55;}
</style>""", unsafe_allow_html=True)

CUSTOM = "Other company…"
VERDICT_STYLE = {
    "strong": ("#065f46", "#d1fae5", "Strong fit"),
    "plausible": ("#1e40af", "#dbeafe", "Plausible fit"),
    "weak": ("#92400e", "#fef3c7", "Weak fit"),
    "not_a_fit": ("#991b1b", "#fee2e2", "Not a fit"),
    "insufficient_evidence": ("#374151", "#e5e7eb", "Insufficient evidence"),
}


def setting(name, default=""):
    if name in os.environ:
        return os.environ[name]
    try:
        return st.secrets.get(name, default)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default


def enabled(name):
    return str(setting(name, False)).lower() in ("true", "1", "yes")


def stat_row(items):
    """Compact inline stats. st.metric renders a large fixed-width card that truncates
    values like "$0.0232" to "$0..." once four sit side by side in a half-width column."""
    chips = "".join(f'<div class="stat"><span>{escape(str(label))}</span><b>{escape(str(value))}</b></div>'
                    for label, value in items)
    st.markdown(f'<div class="stats">{chips}</div>', unsafe_allow_html=True)


def verdict_badge(verdict):
    colour, background, label = VERDICT_STYLE.get(verdict, ("#374151", "#e5e7eb", str(verdict)))
    st.markdown(f'<span class="verdict" style="color:{colour};background:{background};">{escape(label)}</span>',
                unsafe_allow_html=True)


def summary_table(rows):
    # Escape all model text before inserting it into our fixed table layout.
    html = '<table class="summary-table"><thead><tr><th>Question</th><th>Finding</th><th>Evidence</th><th>Gap / uncertainty</th></tr></thead><tbody>'
    for row in rows:
        evidence = escape(row.get("excerpt") or "No supporting excerpt identified.")
        url = row.get("source_url", "")
        if safe_url(url):
            evidence += f'<br><a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(row["source_id"])}</a>'
        elif row.get("source_id"):
            evidence += '<br>' + escape(row["source_id"])
        if row.get("excerpt") and not row.get("excerpt_matches_source"):
            evidence += '<small>Excerpt needs checking against original.</small>'
        html += '<tr>' + ''.join(f'<td>{cell}</td>' for cell in [escape(row["question"]), escape(row["finding"]), evidence, escape(row["uncertainty"])]) + '</tr>'
    st.markdown(html + '</tbody></table>', unsafe_allow_html=True)


def split_sections(text):
    sections = []
    for block in re.split(r"(?m)^## ", text or ""):
        if block.strip():
            heading, _, body = block.partition("\n")
            sections.append((heading.strip(), body.strip()))
    return sections


def render_markdown_sections(text, skip=()):
    for heading, body in split_sections(text):
        if heading in skip:
            continue
        st.markdown(f'<div class="brief-heading">{escape(heading)}</div>', unsafe_allow_html=True)
        if body:
            st.markdown(body)


def provider_timings(entry):
    brief = entry.get("brief")
    cost = provider_cost(entry)
    stat_row([
        ("Search", f"{entry['retrieval_seconds']:.1f}s"),
        ("Model", f"{brief['seconds']:.1f}s" if brief else "—"),
        ("Total", f"{entry['retrieval_seconds'] + brief['seconds']:.1f}s" if brief else "—"),
        ("Cost", f"${cost['total_usd']:.4f}" if cost["total_usd"] is not None else "not priced"),
    ])


@st.cache_data(show_spinner=False)
def load_library(signature):
    """Read every export in saved_runs/. `signature` carries names and mtimes so the cache
    invalidates when you add or replace a file."""
    library = []
    for path in sorted(Path("saved_runs").glob("*.json")):
        try:
            library.append({"path": path.name, "run": load_saved(path.read_text(encoding="utf-8")), "error": None})
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError) as exc:
            library.append({"path": path.name, "run": None, "error": str(exc)})
    return library


def library_signature():
    try:
        return tuple((p.name, p.stat().st_mtime) for p in sorted(Path("saved_runs").glob("*.json")))
    except OSError:
        return ()


def apply_prefill(run):
    """Load a saved run's exact settings into the form so it can be rerun live.

    Only ever called before the input widgets are created: Streamlit refuses to let a
    widget's session_state key be written after that widget exists in the same run.
    The Rerun button therefore stashes the run and triggers a rerun instead."""
    featured = FEATURED_COMPANIES.get(run["company"]) == run["domain"]
    st.session_state["k_mode"] = run["company"] if featured else CUSTOM
    st.session_state["k_name"] = run["company"]
    st.session_state["k_domain"] = run["domain"]
    try:
        st.session_state["k_start"] = date.fromisoformat(run["start_date"])
        st.session_state["k_end"] = date.fromisoformat(run["end_date"])
    except (ValueError, TypeError, KeyError):
        pass
    st.session_state["k_providers"] = [p for p in run.get("providers", {}) if p in PROVIDERS] or list(PROVIDERS)
    st.session_state["rerun_of"] = run.get("id")


keys = {p: str(setting(KEY_NAMES[p])) for p in PROVIDERS}
openai_key = str(setting("OPENAI_API_KEY"))
live_enabled = enabled("ALLOW_LIVE")
password = str(setting("APP_PASSWORD"))
storage_allowed = list(PROVIDERS)

with st.sidebar:
    st.markdown("### Search to Signal")
    st.caption("An SDR research experiment by Iman Barua")
    st.divider()
    st.markdown("**Live access**")
    if live_enabled and password:
        if not st.session_state.get("unlocked"):
            entered = st.text_input("Owner password", type="password")
            if st.button("Unlock live runs"):
                if hmac.compare_digest(entered, password):
                    st.session_state.unlocked = True
                    st.rerun()
                else:
                    st.error("Password does not match.")
        else:
            st.success("Live runs unlocked")
            if st.button("Lock live runs"):
                st.session_state.unlocked = False
                st.rerun()
    else:
        st.caption("Saved examples are available without API access. To enable live runs, follow START_HERE.md.")
    unlocked = bool(live_enabled and password and st.session_state.get("unlocked"))
    if unlocked:
        for p in PROVIDERS:
            st.caption(f"{'✓' if keys[p] else '○'} {p}: {'key configured' if keys[p] else 'key missing'}")
        st.caption(f"{'✓' if openai_key else '○'} OpenAI: {'key configured' if openai_key else 'key missing'}")
    st.divider()
    uploaded = st.file_uploader("Open an exported run", type="json")
    if uploaded is not None and st.button("Load uploaded run"):
        try:
            st.session_state.run = load_saved(uploaded.getvalue().decode("utf-8"))
            st.rerun()
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"Could not open this export: {exc}")
    st.caption("Saved files are snapshots supplied by their author, not independently authenticated API records.")

st.caption("FIVE SEARCH APIS · THREE QUESTIONS · ONE SHARED LLM")
st.title("From search results to a prospect conversation")
st.write("Which retrieval setup helps an SDR prepare a useful, evidence-based conversation with a potential Linkup customer?")

# --- Prospect selection -----------------------------------------------------
# Deliberately outside a form: the custom name/domain fields must appear as soon as
# "Other company…" is chosen, and a form would defer that until submit.
pending_prefill = st.session_state.pop("pending_prefill", None)
if pending_prefill:
    apply_prefill(pending_prefill)

st.session_state.setdefault("k_mode", list(FEATURED_COMPANIES)[0])
st.session_state.setdefault("k_name", "")
st.session_state.setdefault("k_domain", "")
st.session_state.setdefault("k_start", date.today() - timedelta(days=180))
st.session_state.setdefault("k_end", date.today())
st.session_state.setdefault("k_providers", list(PROVIDERS))

with st.container(border=True):
    c1, c2, c3 = st.columns([2, 1, 1])
    mode = c1.selectbox("Prospect", list(FEATURED_COMPANIES) + [CUSTOM], key="k_mode",
                        help="The three saved examples, or any other company by name and domain.")
    c2.date_input("Event window starts", key="k_start", help="Question 2 only. Questions 1 and 3 are undated.")
    c3.date_input("Event window ends", key="k_end", help="Question 2 only. The summary checks event dates, not page dates.")
    if mode == CUSTOM:
        d1, d2 = st.columns(2)
        d1.text_input("Company name", key="k_name", placeholder="Acme Analytics")
        d2.text_input("Official domain", key="k_domain", placeholder="acme.com")
        st.caption("The domain is used to pin the entity in every question. Companies share names; domains do not.")
    st.multiselect("Search providers", list(PROVIDERS), key="k_providers")
    if st.session_state.get("rerun_of"):
        st.info(f"Prefilled from saved run {st.session_state['rerun_of']}. A live run will be linked to it for comparison.")
    n_providers = len(st.session_state["k_providers"])
    st.caption(f"This will make {3 * n_providers} search requests, then up to {n_providers} LLM calls when you generate briefs. "
               "Research retrieves evidence only; generating briefs is a separate action.")
    submitted = st.button("1. Research prospect", type="primary", disabled=not unlocked)

start, end = st.session_state["k_start"], st.session_state["k_end"]
selected = st.session_state["k_providers"]
if mode == CUSTOM:
    company_input, domain_input = st.session_state["k_name"], st.session_state["k_domain"]
else:
    company_input, domain_input = mode, FEATURED_COMPANIES[mode]

if submitted:
    try:
        company = normalise_company_name(company_input)
        domain = normalise_domain(domain_input)
    except ValueError as exc:
        company = domain = None
        st.error(str(exc))
    missing = [p for p in selected if not keys[p]]
    if company and domain:
        if not selected or start >= end:
            st.error("Choose at least one provider. The event window start must be before its end.")
        elif missing:
            st.error("Missing API keys: " + ", ".join(missing))
        elif st.session_state.get("research_runs", 0) >= 10:
            st.error("This session has reached its ten-run safety limit. Restart the app intentionally to run more. This is not a billing cap.")
        else:
            st.session_state.research_runs = st.session_state.get("research_runs", 0) + 1
            with st.status(f"Retrieving evidence: up to {3 * len(selected)} API requests", expanded=True) as status:
                st.session_state.run = research(company, domain, start.isoformat(), end.isoformat(), selected, keys,
                                                on_done=lambda p: st.write(f"{p}: three requests finished. See statuses below."),
                                                rerun_of=st.session_state.get("rerun_of"))
                st.session_state.rerun_of = None
                status.update(label="Research finished. Inspect the evidence below.", state="complete")

run = st.session_state.get("run")
if run:
    st.divider()
    back, _ = st.columns([1, 5])
    if back.button("← All companies"):
        st.session_state.pop("run", None)
        st.rerun()
    st.subheader(f"{run['company']} · {run['domain']}")
    st.caption(f"{'SAVED SNAPSHOT' if run['origin'] == 'saved' else 'LIVE RUN'} · {run['created_at']} · Run {run['id']} · Events: {run['start_date']} to {run['end_date']}")
    if run.get("excluded_providers"):
        st.info("Omitted from this export: " + ", ".join(run["excluded_providers"]))
    if company_input != run["company"] or str(start) != run["start_date"] or str(end) != run["end_date"]:
        st.caption("The form above has different settings. Results below remain from the labelled run until you start new research.")
    stat_row([
        ("Search requests", sum(len(v["records"]) for v in run["providers"].values())),
        ("Retrieval wall time", f"{run.get('retrieval_wall_seconds', 0):.1f}s"),
        ("All requests OK", f"{sum(all(not r['error'] for r in v['records']) for v in run['providers'].values())}/{len(run['providers'])}"),
    ])
    if run.get("excluded_providers"):
        st.caption("Wall time is for the original run, including any providers omitted from this export.")

    evidence_tab, brief_tab, timing_tab, library_tab, method_tab = st.tabs(
        ["Retrieved evidence", "Assessments & briefs", "Timing, cost & review", "Run library", "Method & settings"])

    with evidence_tab:
        st.caption("Short previews of original passages. Expand any card for the complete text. These previews do not shorten the evidence sent to the LLM.")
        q_index = st.radio("Research question", range(3), format_func=lambda i: run["questions"][i]["title"], horizontal=True)
        st.info(run["questions"][q_index]["query"])
        names = list(run["providers"])
        chosen_providers = st.multiselect("Compare evidence from", names, default=names[:2], key=f"compare-{run['id']}")
        for offset in range(0, len(chosen_providers), 2):
            for col, p in zip(st.columns(2), chosen_providers[offset:offset + 2]):
                with col:
                    record = run["providers"][p]["records"][q_index]
                    with st.container(border=True):
                        st.subheader(p)
                        st.caption(f"{record['mode']} · {record['seconds']:.2f}s · HTTP {record['status_code'] or 'n/a'}")
                        if record["error"]:
                            st.error(record["error"])
                        if record.get("credential_redacted"):
                            st.warning("A credential echoed by the service was redacted from the raw response.")
                        if not record["evidence"] and not record["error"]:
                            st.info("No results returned. This does not establish absence of a provider or feature.")
                        for idx, item in enumerate(record["evidence"], 1):
                            with st.container(border=True):
                                source_id = f"{record['question']['id']}-S{idx}"
                                st.markdown(f"<strong>{source_id}</strong> · " + escape(item["title"]), unsafe_allow_html=True)
                                domain_label = urlsplit(item["url"]).netloc if safe_url(item["url"]) else "Source URL unavailable"
                                st.caption(domain_label + (f" · {item['date']} (provider date)" if item["date"] else " · Date unavailable"))
                                st.text(passage_preview(item["text"]) or "No passage returned for this source.")
                                with st.expander("Expand full passage"):
                                    st.text(item["text"] or "No passage returned for this source.")
                                    st.caption("Original returned passage. Provider date is not a verified event date.")
                                if safe_url(item["url"]):
                                    st.link_button("Open source", item["url"])
                        with st.expander("Exact request & full raw response"):
                            st.code(record["endpoint"])
                            st.json(record["request"])
                            st.code(record["raw_text"], language="json")
                            st.json(record.get("response_headers", {}))

    with brief_tab:
        st.caption(f"Shared model: {run['model']}. Each assessment uses only that provider's evidence plus the same "
                   "Linkup product and ICP context. No search tools are available to the LLM.")
        pending = [p for p, v in run["providers"].items() if not (v.get("brief") or {}).get("evidence_summary")]
        st.caption("One LLM call per provider produces the fit assessment, the summary, the brief and the deep dive. "
                   "No automated reviewer or score. Older results can be refreshed from their existing evidence.")
        if st.button(f"2. Generate assessments & briefs ({len(pending)} pending)",
                     disabled=not (unlocked and openai_key and pending and run["origin"] == "live")):
            with st.status("Writing assessments from existing evidence", expanded=True) as status:
                for p in pending:
                    entry = run["providers"][p]
                    new_brief = generate_brief(run, p, openai_key)
                    if entry.get("brief"):
                        entry.setdefault("previous_briefs", []).append(entry["brief"])
                    entry["brief"] = new_brief
                    st.write(f"{p}: generation finished.")
                status.update(label="Generation finished", state="complete")
        if run["origin"] == "saved":
            st.caption("Replay mode does not make API calls. Use the Run library tab to rerun this exact setup live.")

        cards = ""
        for p, entry in run["providers"].items():
            fit = (entry.get("brief") or {}).get("fit") or {}
            verdict = fit.get("verdict")
            colour, background, label = VERDICT_STYLE.get(verdict, ("#374151", "#e5e7eb", "Not generated"))
            confidence = fit.get("confidence")
            cards += (f'<div class="strip-card"><b>{escape(p)}</b>'
                      f'<span class="verdict" style="color:{colour};background:{background};">{escape(label)}</span>'
                      + (f'<small>{escape(confidence)} confidence</small>' if confidence else "")
                      + '</div>')
        if cards:
            st.markdown(f'<div class="strip">{cards}</div>', unsafe_allow_html=True)
        stated = {((v.get("brief") or {}).get("fit") or {}).get("verdict") for v in run["providers"].values()}
        stated.discard(None)
        if len(stated) > 1:
            st.caption("The providers disagree. Same company, same questions, same model, same ICP: the only variable "
                       "is what each search API returned. That disagreement is the result worth discussing.")

        for offset in range(0, len(run["providers"]), 2):
            for col, p in zip(st.columns(2), list(run["providers"])[offset:offset + 2]):
                with col, st.container(border=True):
                    st.subheader(p)
                    entry = run["providers"][p]
                    brief = entry.get("brief")
                    provider_timings(entry)
                    if not brief:
                        st.info("Inspect the evidence, then generate assessments above.")
                        continue
                    if brief.get("error"):
                        st.error(brief["error"])
                    issues = brief.get("checks", [])
                    if issues:
                        with st.expander(f"{len(issues)} thing(s) to check in this output"):
                            for issue in issues:
                                st.write("- " + issue)

                    fit = brief.get("fit")
                    if fit:
                        verdict_badge(fit.get("verdict"))
                        st.caption(f"Confidence: {fit.get('confidence', 'unstated')}")
                        st.text(fit.get("rationale", ""))
                        if not fit.get("entity_confirmed", True):
                            st.error("Entity not confirmed: " + str(fit.get("entity_note", "")))
                        with st.expander("Signals behind this verdict"):
                            st.markdown("**ICP signals present**")
                            for item in fit.get("icp_signals_present") or []:
                                st.text(f"[{item.get('source_id', '')}] {item.get('signal', '')}")
                            if not fit.get("icp_signals_present"):
                                st.caption("None listed.")
                            st.markdown("**Disqualifying signals**")
                            for item in fit.get("disqualifying_signals") or []:
                                st.text(f"[{item.get('source_id', '')}] {item.get('signal', '')}")
                            if not fit.get("disqualifying_signals"):
                                st.caption("None listed.")
                            st.markdown("**Evidence gaps**")
                            st.text(fit.get("evidence_gaps", ""))

                    if brief.get("evidence_summary"):
                        st.caption("LLM-GENERATED EVIDENCE SUMMARY · CHECK AGAINST THE SOURCES")
                        summary_table(brief["evidence_summary"])
                    elif not brief.get("error"):
                        st.info("This older result has no summary. The original brief remains below.")

                    email_body = dict(split_sections(brief.get("text", ""))).get("First-touch email", "")
                    if email_body:
                        st.markdown("**First-touch email**")
                        st.markdown(f'<div class="email-card">{escape(email_body)}</div>', unsafe_allow_html=True)
                        words = brief.get("email_word_count", "n/a")
                        note = " · no email drafted" if brief.get("email_suppressed") else ""
                        st.caption(f"{words} words{note} · draft, needs a factual check before sending")
                    with st.expander("Read the full prospect brief"):
                        render_markdown_sections(brief.get("text", ""), skip=("First-touch email",))
                    if brief.get("deep_dive"):
                        with st.expander("Deep dive: objections, stakeholders, first call"):
                            render_markdown_sections(brief["deep_dive"])
                            st.caption("Internal preparation, not customer-facing copy.")

                    bundle, _ = evidence_bundle(entry["records"])
                    with st.expander("Citation directory & exact LLM input"):
                        for group in bundle:
                            for source in group["sources"]:
                                if safe_url(source["url"]):
                                    st.link_button(f"{source['id']} · {source['title'][:70]}", source["url"])
                        st.dataframe(brief["stats"], hide_index=True)
                        st.caption(f"Prompt hash {brief.get('prompt_sha256', '')[:16]} · context {brief.get('context_version', '?')}")
                        st.code(brief.get("input", ""), language="json")
                        st.code(brief.get("instructions", ""))
                        st.json(brief.get("settings", {}))
                        st.code(brief.get("raw_text", ""), language="json")
                    if p in storage_allowed and brief.get("text"):
                        st.download_button("Download brief", brief["text"], f"{run['company']}-{p}-brief.md", key=f"brief-{run['id']}-{p}")

    with timing_tab:
        rows = []
        for p, v in run["providers"].items():
            brief = v.get("brief")
            cost = provider_cost(v)
            rows.append({"Provider": p, "Mode": MODES[p],
                         "Verdict": ((brief or {}).get("fit") or {}).get("verdict", "no brief"),
                         "Successful searches": sum(not r["error"] for r in v["records"]),
                         "Q1 seconds": round(v["records"][0]["seconds"], 2), "Q2 seconds": round(v["records"][1]["seconds"], 2),
                         "Q3 seconds": round(v["records"][2]["seconds"], 2), "Retrieval elapsed seconds": round(v["retrieval_seconds"], 2),
                         "Summary + brief seconds": round(brief["seconds"], 2) if brief else None,
                         "Active pipeline seconds": round(v["retrieval_seconds"] + brief["seconds"], 2) if brief else None,
                         "Search $": cost["search_usd"], "LLM $": cost["llm_usd"], "Total $": cost["total_usd"]})
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption("Providers run concurrently; questions run sequentially within each provider. Active pipeline time is retrieval elapsed + LLM request time. It excludes your review pause, other providers' LLM calls and UI rendering. Times include network overhead. Errors are retained; there are no automatic retries.")
        st.caption(f"Costs combine provider-reported figures where returned with list-price estimates checked on {COST_CHECKED_ON}. "
                   "Blank means no price is configured for that provider, which is not the same as free. Your dashboards are authoritative.")
        st.markdown("**Manual review**")
        st.write("For each brief: verify the company, check whether each citation supports its claim, inspect primary sources, distinguish event dates from page dates, and note missing evidence or edits needed before outreach. More sources or smoother prose do not automatically mean better research. Judge the fit verdict separately from the writing.")
        review_provider = st.selectbox("Review provider", list(run["providers"]))
        field = f"review-{run['id']}-{review_provider}"
        initial = run["providers"][review_provider].get("review", "")
        note = st.text_area("Your evidence checks, gaps and correction notes", value=initial, key=field)
        run["providers"][review_provider]["review"] = note
        with st.expander("Usage returned by providers"):
            for p, v in run["providers"].items():
                st.write(p)
                st.json({"search": [{"question": r["question"]["id"], "usage": r.get("usage"), "provider_cost_estimate": r.get("provider_cost_estimate")} for r in v["records"]], "llm_tokens": (v.get("brief") or {}).get("usage")})
            st.caption("Null means not reported, not free. Exa cost fields are estimates. Provider dashboards are authoritative for billing.")

    with library_tab:
        st.markdown("**Saved runs**")
        st.caption("Every export in saved_runs/. Open one to replay it, or rerun its exact settings live.")
        library = load_library(library_signature())
        good = [item for item in library if item["run"]]
        for item in library:
            if item["error"]:
                st.error(f"{item['path']}: {item['error']}")
        if not good:
            st.info("No saved runs yet. Run a company, then use Save run for replay and move the JSON into saved_runs/.")
        else:
            table = []
            for item in good:
                summary = run_summary(item["run"])
                table.append({"File": item["path"], "Company": summary["company"], "Domain": summary["domain"],
                              "Run": summary["id"], "Created": summary["created_at"], "Window": summary["window"],
                              "Providers": ", ".join(summary["providers"]),
                              "Verdicts": ", ".join(f"{p}:{v}" for p, v in summary["verdicts"].items())})
            st.dataframe(table, hide_index=True, width="stretch")

            labels = {f"{item['run']['company']} · {item['run']['id']} · {item['run']['created_at'][:10]}": item
                      for item in good}
            picked = st.multiselect("Select runs to compare or open", list(labels))
            if picked:
                comparison = []
                for name in picked:
                    chosen = labels[name]["run"]
                    summary = run_summary(chosen)
                    for p, entry in chosen["providers"].items():
                        cost = provider_cost(entry)
                        comparison.append({"Run": summary["id"], "Company": summary["company"],
                                           "Window": summary["window"], "Provider": p,
                                           "Verdict": summary["verdicts"].get(p),
                                           "Retrieval s": round(entry.get("retrieval_seconds", 0), 2),
                                           "Total $": cost["total_usd"]})
                st.dataframe(comparison, hide_index=True, width="stretch")

                if len(picked) == 1:
                    single = labels[picked[0]]["run"]
                    o1, o2 = st.columns(2)
                    if o1.button("Open this run"):
                        st.session_state.run = single
                        st.rerun()
                    if o2.button("Rerun these settings live", disabled=not unlocked):
                        st.session_state["pending_prefill"] = single
                        st.rerun()

    with method_tab:
        st.write(run["execution"])
        st.markdown("**Linkup context**")
        st.write("Every brief in this run was generated with the same Linkup product and ICP context. It is "
                 "byte-identical across all five providers, so it cannot advantage one provider's evidence, and it is "
                 "desk research from public sources rather than output from any provider in this comparison. The fit "
                 "verdict is judged against the ICP definition in that block.")
        with st.expander("Read the exact Linkup context used"):
            st.json(LINKUP_CONTEXT)
        st.write(f"Source previews are display-only excerpts of up to 320 characters. The evidence budget is unchanged. A single "
                 f"shared-LLM call produces the fit assessment, the three-row summary, the brief and the deep dive, with up to "
                 f"{MAX_OUTPUT_TOKENS} output tokens. There is no reviewer or grading step. Timings are not comparable with runs "
                 "made under earlier output formats.")
        st.write("The same question text and dates go to each provider. Parallel additionally requires a keyword query, generated by a fixed template and shown in the manifest. No provider-specific hints about known incumbents are injected. Known limitation: the question text is written as a natural-language objective, which suits objective-based APIs more than keyword-based ones. This is disclosed rather than corrected in this version.")
        st.write(f"Up to 10 results are requested where supported. Linkup is queried at depth '{run.get('linkup_depth') or LINKUP_DEPTH}'; it also offers flash, fast and deep, which are not compared here. Parallel v1 uses a total excerpt character limit instead. Each LLM gets at most 12,000 serialized evidence characters per question, in provider ranking order. The last fitting passage may be cut; unused budget is not transferred between questions. All returned evidence remains visible above.")
        st.write("All questions search the open web without domain restrictions. Prompts prefer useful primary evidence and discourage generic educational blogs. Questions 1 and 3 have no date filters; historical technical evidence must not be presented as confirmed current usage.")
        st.write("Question 2 uses the dates selected in the form. Linkup receives fromDate/toDate; Exa receives startPublishedDate/endPublishedDate; Tavily receives start_date/end_date with strict date filtering (undated results are removed); Brave receives a custom freshness range. Parallel supports after_date only: the end date stays in its prompt and requires review. Filters differ: publication dates and page updates are not event dates. The summary must check the actual event date and distinguish the last 90 days from earlier developments within your window. These filters do not reconstruct a historical snapshot of the web.")
        st.write("An identical model cannot eliminate retrieval, source-volume or provider-internal synthesis differences.")
        for p, v in run["providers"].items():
            with st.expander(f"{p}: endpoint, parameters and evidence budget"):
                st.link_button("Official documentation", DOCS[p])
                st.json([{"endpoint": r["endpoint"], "request": r["request"]} for r in v["records"]])
                _, stats = evidence_bundle(v["records"])
                st.dataframe(stats, hide_index=True)
        st.caption("This is one example run on a selected prospect, not a universal benchmark or proof of demand. For repeat trials, export every run, including failures, and compare the same settings.")

    st.divider()
    export = export_run(run, list(run["providers"]))
    st.download_button("Save run for replay", json.dumps(export, indent=2, ensure_ascii=False),
                       f"{run['company']}-{run['id']}.json", mime="application/json")
    st.caption("Download, then drop the file into saved_runs/ to keep it as an example.")
else:
    st.divider()
    cols = st.columns(3)
    for col, title, body in zip(cols, ["01 · Product fit", "02 · Why now?", "03 · Existing approach"],
                               ["Find documented workflows using external web information.", "Find relevant launches and integrations in a fixed date window.", "Find evidence of current search APIs and data providers."]):
        with col, st.container(border=True):
            st.subheader(title)
            st.write(body)
    st.write("Each provider's evidence then produces a fit verdict against a fixed Linkup ICP definition. "
             "Not a fit and insufficient evidence are permitted outcomes, and are the right answer for many companies.")

    library = load_library(library_signature())
    good = [item for item in library if item["run"]]
    if good:
        st.markdown("**Saved examples**")
        for item in good:
            summary = run_summary(item["run"])
            with st.container(border=True):
                left, right = st.columns([3, 1])
                left.write(f"**{summary['company']}** · {summary['domain']}")
                left.caption(f"{summary['created_at'][:10]} · {summary['window']} · "
                             + ", ".join(f"{p}: {v}" for p, v in summary["verdicts"].items()))
                if right.button("Open", key=f"open-{summary['id']}"):
                    st.session_state.run = item["run"]
                    st.rerun()
    else:
        st.info("Ready for your first run. Configure the keys in .streamlit/secrets.toml, then unlock live access in the sidebar.")

    with st.expander("See the exact questions and provider settings"):
        for question in questions(company_input or "[company]", domain_input or "[domain]", str(start), str(end)):
            st.write(question["query"])
        st.table([{"Provider": p, "Mode": MODES[p]} for p in PROVIDERS])
st.caption("Built for thoughtful prospecting. Hypotheses require qualification. Emails are drafts only.")
