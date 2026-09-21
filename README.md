# Search to Signal

A small Streamlit experiment by Iman Barua: compare five retrieval APIs while researching a company as a prospective Linkup customer. See **START_HERE.md** for installation.

Three separate research questions go to Linkup, Exa, Parallel, Tavily and Brave. Each provider's evidence is shown raw, then a single shared LLM turns that one provider's evidence into a fit verdict, an evidence summary, a prospect brief and an internal deep dive. Nothing is mixed across providers.

## How it works

Pick a company by name and domain, or one of the three saved examples. Three research questions go to all
five providers with the same wording and the same dates. You see every provider's raw evidence first. Then
one shared LLM turns each provider's evidence, on its own, into a fit verdict, a three-row evidence summary,
a prospect brief and an internal deep dive.

The verdict is **strong**, **plausible**, **weak**, **not a fit** or **insufficient evidence**, judged against
the ICP definition in `linkup_context.py`. The last two are real answers, not failures. Each signal behind a
verdict has to cite a source that was actually retrieved.

Where providers disagree on the same company, that disagreement is the point: same questions, same model,
same ICP, so the only variable is what each search API found.

`linkup_context.py` holds the Linkup product and ICP description that every brief is built on: endpoints,
pricing shape, published customers, benchmark claims, competitive set, buying signals and anti-signals.
It is desk research from public sources, and the same bytes go to all five providers so it cannot favour one.
Edit it freely; it is the file that encodes what you think Linkup's ICP is.

## Search policy 2.0

All questions search the open web with no domain allowlists, blocklists or site operators. Q1 asks for documented workflows, preferring current product, documentation and integration pages. Q2 asks for launches, integrations or expansions inside the selected window, preferring announcements, changelogs and release notes. Q3 asks for technical evidence with scope and dates, distinguishing production use from tutorials, benchmarks and historical evidence. These are prompt preferences, not guaranteed source types.

| Provider | Q2 date settings | Limitation |
| --- | --- | --- |
| [Linkup](https://docs.linkup.so/pages/documentation/endpoints/search/reference) | `fromDate`, `toDate` | Source-date constraints do not verify event dates. |
| [Exa](https://exa.ai/docs/reference/search) | `startPublishedDate` 00:00:00 UTC, `endPublishedDate` 23:59:59.999 UTC | Publication dates may differ from the event date. |
| [Parallel](https://docs.parallel.ai/resources/source-policy) | `advanced_settings.source_policy.after_date` | Only a lower bound is documented. The end date sits in the objective and must be checked in the evidence. |
| [Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search) | `start_date`, `end_date`, `filter_by_published_date: true` | Dates may represent updates; undated results are excluded. |
| [Brave](https://api-dashboard.search.brave.com/api-reference/web/search/get) | `freshness: YYYY-MM-DDtoYYYY-MM-DD` | Page age can use publication or modification dates. |

Boundary and missing-date behaviour differ across providers. The shared LLM is instructed to reject unsupported or out-of-window event dates. That is synthesis guidance, not an independent reviewer. No raw results are silently deleted, and date filters do not reconstruct historical web snapshots.

## Method

Ask three separate questions: documented product fit, recent relevant developments, and existing retrieval approach. Show original passages and complete raw response bodies before generating anything. Use one pinned model per provider evidence bundle, identical instructions and limits, no tools, and no cross-provider evidence.

**Known limitation, disclosed rather than fixed in this version:** the question text is written as a natural-language objective. That suits objective-based APIs more than keyword-based ones, and Parallel additionally receives a templated keyword query because its API requires one. A fairer design would carry both an objective and a keyword form per question and give each provider whichever its own documentation recommends. This version does not do that.

## Configurations checked 21 September 2026

| Provider | Configuration | Rationale and limitation |
|---|---|---|
| [Linkup](https://docs.linkup.so/pages/documentation/endpoints/search/reference) | `/v1/search`, depth `standard`, `searchResults`, maxResults 10 | Instruction-aware retrieval; source content without a generated answer. Linkup also documents `flash`, `fast` and `deep`; `standard` is the closest match to the other providers' default behaviour. The depth is recorded in every run, and comparing across depths is a different experiment. |
| [Exa](https://exa.ai/docs/reference/search) | `/search`, auto, 10 results, highlights | Documented balanced mode with source passages. |
| [Parallel](https://docs.parallel.ai/api-reference/search/search) | `/v1/search`, basic, objective plus one fixed keyword query, max_chars_total 12000 | Its required keyword field is a disclosed adapter difference. Docs recommend 2-3 keyword queries; one is used. |
| [Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search) | `/search`, basic, 10 results, 3 chunks/source | Fixed general-purpose mode, automatic mode selection off. |
| [Brave](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started) | `/res/v1/web/search`, 10 results, extra snippets | Deliberate general web-search baseline, not a recreation of any chatbot's search stack. |
| [OpenAI](https://developers.openai.com/api/docs/models/gpt-4.1-mini) | gpt-4.1-mini-2025-04-14, Responses API, temperature 0, max output 7000, store false | Economical pinned snapshot for synthesis. Not a claim that it is the newest or strongest model. No tools provided. |

All requests use the same standard-library HTTP transport. No SDK retries, hidden post-search fetches or fallback modes. Provider-internal retrieval work is included in its measured request duration.

## Evidence and timing

- Normalisation copies each provider's configured passage fields and source metadata; it does not paraphrase. Raw response text is retained. If a service echoes its API key, that string is redacted and visibly flagged.
- LLM evidence budget: 12,000 serialized characters per question, 36,000 total. A character budget, not equal tokens. Returned vs sent counts are visible; ranking order is preserved; a final fitting passage may be truncated with its URL retained. No hidden reranking, deduplication or external extractor.
- Five providers run concurrently; each provider's three questions run sequentially; generation runs sequentially across providers. Active pipeline time is provider retrieval elapsed plus that provider's generation, excluding your review pause and UI work.
- Socket timeout is 90 seconds per blocking operation. Failed calls remain in the results. No automatic retries.
- Citation IDs are checked for existence and excerpts for exact match. Neither checks entailment. There is no LLM grader and no lead score.

## Interpreting the experiment

Assess claim support before prose. Verify identity, primary sources, event dates, incumbent scope, missing facts and correction effort. A polished email is not proof of accurate research, and a confident verdict is not proof of a real opportunity. Compare repeated trials under the same policy, context version and window, keep failures, and report sample size.

A public announcement is not buying intent. A pain hypothesis is not a verified problem. This app deliberately does not declare a winner.

## Files

- `app.py`: Streamlit interface, secret loading, run library, export and replay controls.
- `core.py`: request adapters, identity validation, timing, normalisation, evidence budgets, shared prompt, cost model, save/load.
- `linkup_context.py`: the frozen Linkup product and ICP context injected into every brief.
- `validate_saved_runs.py`: pre-commit check for everything in `saved_runs/`.
- `tests/`: synthetic fixtures only, never real saved results.
- `saved_runs/`: permitted exports created from actual live requests.
- `secrets.example.toml`: blank configuration template.

## Storage

Export is opt-in per provider. [Brave's FAQ](https://brave.com/search/api/) requires explicit storage rights; confirm your plan before enabling its flag. Confirm other vendors' terms before sharing raw results. No comparison file or credential is saved automatically; downloading an export is an explicit action.

Built locally and tested with synthetic transport responses. Version 2.0 changes the request path only where noted, but its prompt, output schema and saved-run format are new and need a live run with your own credentials before you rely on them.
