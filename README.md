# SignalDesk

### Evidence before execution.

A local-first GTM workspace for turning account lists into scored, reviewable distribution drafts. Original software, inspired by the workflow category, not a Clay clone or a claim of feature parity. SignalDesk is a provisional working name.

## Run in one minute

Python 3.10 or newer. No Python packages, API keys, credit card or cloud service required.

```sh
python3 server.py
```

Open **http://127.0.0.1:8787**. Click **Try sample data**, then **Run workflow**. Samples are explicitly fictional and use reserved `.example` domains.

1. Import your CSV or add an account. Normalize and deduplicate by domain.
2. Configure your industry, region, team-size bounds, offer and call to action in Workflow.
3. Run the pipeline. Each record gets a step-by-step scoring trace.
4. Open drafts, check evidence, edit the words and mark individual records reviewed.
5. Export reviewed, non-suppressed drafts as CSV. Nothing is sent.

## What works

| Capability | Status |
| --- | --- |
| CSV import, quoted fields/newlines, validation, atomic rejection | Implemented and tested |
| Domain normalization, deduplication, individual account creation/deletion | Implemented and tested |
| Configurable ICP scoring, source-presence points and readable traces | Implemented and tested; deterministic, not AI |
| Account evidence note + source URL | User-supplied only, not independently verified |
| Template draft generation, editing, suppression and review gate | Implemented and tested |
| SQLite persistence, run snapshots and CSV export | Implemented and tested |
| Local Ollama generation | Optional adapter implemented; no real-model inference validated in this release |
| Email discovery/verification, enrichment waterfall, CRM sync, schedules, campaign delivery, analytics | Not implemented |
| Multi-user auth, internet hosting, tenant isolation | Not implemented; do not expose this local server |

## Optional local AI

Template mode is the default, clearly labeled in the UI. To use an already-installed local [Ollama](https://ollama.com/) model:

```sh
SIGNALDESK_ENABLE_OLLAMA=1 SIGNALDESK_MODEL=qwen2.5:3b python3 server.py
```

Enable local AI in Workflow and save before running. The adapter calls only `http://127.0.0.1:11434/api/generate`. No cloud endpoint or API key is used. Install/run the model separately; it is not included. Machine requirements and model licenses depend on your selection. Account data is passed to the local model as untrusted input, and all output requires human review. Local models can still hallucinate or follow malicious source text. Failures appear in the run trace, with no silent template fallback. Requests can take up to 90 seconds per qualified account. Real inference has not been validated in this release.

## CSV format

Required columns: `company,domain`.

Optional: `industry,region,size,contact,evidence,source,suppressed`.

```csv
company,domain,industry,region,size,contact,evidence,source,suppressed
Northstar Demo,northstar.example,SaaS,India,48,,Fictional signal: growing sales team,https://northstar.example/news,false
```

Maximum 500 records per import, 2 MB request limit. `size` is a nonnegative integer or blank. `source` must be an HTTP(S) URL. `suppressed` accepts true/1/yes. Missing fields earn no matching points. Source presence is not verification or confidence. No emails are guessed or validated.

## Safety and data

- Binds to loopback only. Host and Origin checks protect local endpoints from routine cross-origin requests. No CORS allowance. This is a single-user local tool, not a production internet server.
- SQLite stays in `signaldesk.sqlite3`, or set `SIGNALDESK_DB` to another path. Do not commit your database or exported prospect data. Back up the database with the server stopped.
- No telemetry, trackers, remote fonts, delivery credentials or send endpoint. No website scraping. Source URLs are not fetched by the app.
- Edits, settings changes and reruns reset review marks. Suppressed records are excluded from drafts and exports. Changing suppression also resets review.
- CSV output protects spreadsheet formula prefixes. HTML views escape imported text. A user-supplied source link is not automatically safe: review the destination before opening it.
- Export approval is local workflow state, not contact permission, legal advice, email validation or approval to send. Honor opt-outs, privacy rules, marketing rules and platform terms before using data elsewhere.
- No auto-retention policy or database encryption. Keep the machine and backups secure. Local administrators can access stored data.

## Tests

```sh
python3 -m unittest -v
# Optional browser test, requires Node.js and Chrome:
npm install
npm run test:e2e
```

20 Python unit/API tests cover scoring, dedupe, atomic imports, quoted CSV, persistence, opt-in AI failures, review invalidation, suppression, export safety, validation and HTTP origin/content-type boundaries. Browser E2E covers import, run, review/export gate, edit invalidation, reload persistence, search/filter, suppression, configuration, run traces and all five views at 320px/390px. No real contacts or sends are used.

## Architecture

`server.py`: local HTTP API, SQLite store, scoring, pipeline, templates and optional Ollama adapter.

`index.html`: dependency-free responsive application UI.

`test_server.py`: standard-library tests. `e2e.cjs`: optional Playwright browser test.

## Product direction

The first wedge is a trustworthy account-to-draft loop. Further work: real source retrieval with provenance and fetch safeguards, validated local AI, configurable workflow nodes, explicit provider cost controls, CRM adapters, consent-aware approved delivery and outcome feedback. Those are future work, not working features today.

Category references, checked October 20, 2026: [Clay workflows](https://www.clay.com/workflows), [Clay developer workflow guide](https://developers.clay.com/use-cases/run-gtm-workflows). These were used for category understanding only; no Clay source code, assets or branding were copied.
