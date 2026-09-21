# Run Search to Signal on your Mac

Your existing VS Code folder and activated Python environment are ready.

## Updating an existing installation

Copy in `app.py`, `core.py`, `linkup_context.py`, `validate_saved_runs.py` and `tests/`. Keep
`.streamlit/secrets.toml`, `.venv` and everything in `saved_runs/`. No new dependencies, no new keys.

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

## First installation

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p .streamlit
cp -n secrets.example.toml .streamlit/secrets.toml
```

Open `.streamlit/secrets.toml`, paste each API key, and set `APP_PASSWORD` to anything you like: it unlocks
live runs. Then `python -m streamlit run app.py`, unlock in the sidebar, pick a company and click
**1. Research prospect**, then **2. Generate assessments & briefs**.

Optionally fill in `SEARCH_COST_ESTIMATE_USD` in `core.py` with your real per-request prices so the cost
column is complete. Linkup and Brave are prefilled.

## Researching any company

Choose **Other company…** in the prospect selector and enter a name and domain. Paste the domain however you have it; `https://www.acme.com/pricing` is accepted and stored as `acme.com`. The domain pins the entity in all three questions, so get it right: several companies share a name, and the app will tell you when the retrieved evidence looks like a different organisation.

Try at least one company that should **not** fit — a consultancy, a hardware shop, a business with no software product. A demo that returns "strong fit" for everything is worth nothing, and seeing the app return *not a fit* with a disqualifying signal is the most convincing thing it does.

## Saved examples and sharing

There are no prefilled results in the download. Run Unify, Dust and Taktile with the same dates and providers so they are comparable with each other.

Use **Save run for replay** at the bottom of the page. Download each run before starting another; live results are not written to disk automatically. Then:

```bash
mv ~/Downloads/Dust-*.json saved_runs/
python validate_saved_runs.py
```

The validator opens every file the way the app does, prints the company, window, policy, context version and verdicts, warns on credential-like strings, and exits non-zero if anything is unreadable. Run it before every commit. A saved run that fails to open shows as an error in the run library, which is a bad thing to discover while presenting.

Brave's FAQ explicitly requires a plan granting storage rights. Its default flag is false, so its results and derived brief are omitted from exports while the live view still works.

For Streamlit Community Cloud, push to a GitHub repository including only reviewed, permitted saved examples. Choose `app.py` as the entrypoint. Add secrets through the host's secrets settings, never the repository. For a shareable demonstration set `ALLOW_LIVE = false` and let people explore saved runs without keys; alternatively keep password-protected live mode for yourself. The per-session ten-run limit is a convenience, not an account-wide spending cap. Set vendor spending limits separately, especially before rerunning everything.

## If something fails

- `ModuleNotFoundError: linkup_context`: `linkup_context.py` is not beside `core.py`. Move it out of any subfolder.
- `ModuleNotFoundError: streamlit`: activate `.venv` and run the requirements install again.
- Python SSL certificate errors: run **Install Certificates.command** from your Python folder in Applications, then restart. Never disable TLS verification.
- HTTP 401/403: check that provider's key and API permissions.
- HTTP 429: check rate limits or credits. There are no automatic retries. Select just the failed provider for a separately labelled new run.
- HTTP 400/422: inspect the request and raw response. Copy the error without API keys so the integration can be adjusted.
- "Model stopped before finishing (incomplete: max_output_tokens)": raise `MAX_OUTPUT_TOKENS` in `core.py`. The evidence is unaffected; regenerate from the same run.
- A brief warning about unknown citation IDs or an unsupported verdict: that is the app working. Read the evidence and judge it yourself.
- Stop the app with Ctrl+C. Restart after editing secrets or `linkup_context.py`.

## Verification

```bash
python -m unittest discover -s tests
```

46 tests covering identity validation, context freezing and byte-identical injection across providers, date handling, evidence isolation and truncation, fit-verdict citation checks, entity-check surfacing, email suppression, truncated-response handling, cost arithmetic, saved-run compatibility across schema versions, and the Streamlit screens. Fixtures are explicitly synthetic. They do not establish live API compatibility, account access or result quality. Complete those checks with your own first live run.
