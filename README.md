# SignalDesk

### Evidence before execution.

A local-first GTM preparation product for turning account lists into scored, reviewable distribution drafts. Original software, inspired by the workflow category, not a Clay clone or a claim of feature parity. SignalDesk is a provisional working name.

## Run in one minute

Python 3.10 or newer. No Python packages, API keys, credit card or cloud service required for the default template mode.

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
| Public homepage research, robots checks, bounded HTML, timestamp/hash | Implemented; actual example.com and Clay homepages fetched, not independent fact verification |
| Manual account evidence note + source URL | User-supplied, not independently verified |
| Email, LinkedIn and partnership templates, editing, suppression and review gate | Implemented and tested |
| Distribution experiment board, manual funnel metrics and learning log | Implemented and tested, no automatic publishing/tracking |
| Durable asynchronous batch research -> scoring -> drafts, cancellation and restart recovery | Implemented and tested |
| SQLite persistence, workspace JSON backup, run snapshots and CSV export | Implemented and tested |
| Local GGUF AI value question | Actual Qwen 2.5 1.5B Q4 inference tested; optional install, human review required |
| Local Ollama generation | Optional adapter implemented; Ollama-specific path not live-tested |
| Email discovery/verification, enrichment waterfall, CRM sync, schedules, campaign delivery, automated analytics | Not implemented |
| Multi-user auth, internet hosting, tenant isolation | Not implemented; do not expose this local server |

## Optional real local AI

Template mode works with no dependencies. For real local inference, install the optional CPU runtime separately:

```sh
python3 -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

Download `qwen2.5-1.5b-instruct-q4_k_m.gguf` from the official [Qwen model repository](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF), then run:

```sh
SIGNALDESK_GGUF=/absolute/path/to/qwen2.5-1.5b-instruct-q4_k_m.gguf python3 server.py
```

Enable local AI in Workflow and save before running. Tested with llama-cpp-python 0.3.36 and that Qwen model: real inference completed in about five seconds on the test machine for one fictional account. Timing depends on hardware. No model weights are bundled. Model license is Apache 2.0 per its official repository; runtime license is MIT per its documentation. These are third-party components, not original project assets.

AI is intentionally narrow: it suggests one value question from the seller offer. It does **not** invent account facts or write a whole personalized email. The rest of the draft is a deterministic template. The initial small-model full-email experiment confused sender/recipient and added claims, so that approach was rejected. Even a bounded question can be poor or incorrect. Human review is required. Format checks reject incomplete output; they are not semantic truth guarantees.

Alternative, unvalidated Ollama path: start an already-installed model, then `SIGNALDESK_ENABLE_OLLAMA=1 SIGNALDESK_MODEL=qwen2.5:1.5b python3 server.py`. This calls only `http://127.0.0.1:11434/api/generate`. No cloud provider or API key is used. Account research is not passed to the model; only the seller offer is used for the question. The app fails visibly in run history rather than silently falling back.

## Public homepage research

Open an account, then **Research public homepage**. This replaces evidence with a text excerpt, title, timestamp, URL and SHA-256 content hash; it clears the draft, score and review. It does not independently verify the page's claims.

Research is a single explicit action, not a crawler or scheduler. Only the company's HTTPS homepage is requested, after robots.txt checks. Private/reserved IPs, mixed DNS answers, credentials in URLs, non-443 ports, cross-host redirects and oversized pages are rejected. Connections are pinned to the validated IP with TLS hostname verification. No cookies, JavaScript execution, login, API keys or contact discovery. Email addresses and phone-like strings are removed from the visible excerpt. Limits: 500 KB/page, 8-second connection/read timeout, two same-host redirects, one research request/domain/minute. Sites requesting crawl delay, failing robots policy checks or needing browser rendering should use manual evidence instead. A failure preserves previous evidence.

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
- No telemetry, trackers, remote fonts, delivery credentials or send endpoint. Public homepage fetching happens only when explicitly requested. No background scraping or contact collection. Source links can still lead to unsafe content.
- Edits, settings changes and reruns reset review marks. Suppressed records are excluded from drafts and exports. Changing suppression also resets review.
- CSV output protects spreadsheet formula prefixes. HTML views escape imported text. A user-supplied source link is not automatically safe: review the destination before opening it.
- Export approval is local workflow state, not contact permission, legal advice, email validation or approval to send. Honor opt-outs, privacy rules, marketing rules and platform terms before using data elsewhere.
- No auto-retention policy or database encryption. Keep the machine and backups secure. Local administrators can access stored data.

## Tests

```sh
python3 -m unittest -v
# Optional actual model test:
SIGNALDESK_GGUF=/path/to/model.gguf python3 -m unittest test_ai -v
# Optional browser test, requires Node.js and Chrome:
npm install
npm run test:e2e
# Optional real public-fetch + local-model UI integration:
SIGNALDESK_GGUF=/path/to/model.gguf npm run test:integration
```

36 Python unit/API/job tests plus one opt-in actual-model test cover scoring, dedupe, atomic imports, quoted CSV, persistence, opt-in AI failures, review invalidation, suppression, export safety, validation and HTTP origin/content-type boundaries. Browser E2E covers import, run, review/export gate, edit invalidation, reload persistence, search/filter, suppression, configuration, run traces, experiment create/update, manual launch guard and funnel arithmetic and all seven views at 320px/390px. Actual public-research + AI browser integration also passed: example.com homepage capture, provenance display, local GGUF inference, partnership draft, desktop and 320px review UI. No real contacts or sends are used. Set `CHROME_PATH` if Chrome is not at `/usr/bin/google-chrome`. Optional dependencies and model files need their own installation; the base app remains dependency-free.

## Architecture

`server.py`: local HTTP API, SQLite store, scoring, pipeline, templates and optional Ollama adapter.

`index.html`: dependency-free responsive application UI.

`jobs.py`: durable batch worker. `research.py`: bounded public homepage research. `test_server.py`: standard-library tests. `test_ai.py`: opt-in real GGUF inference test. `e2e.cjs`: optional Playwright browser test.

## Automated account preparation

In Automation, select 1-25 accounts, optionally refresh their public homepage evidence, then start a batch. The durable job snapshots the playbook, runs research -> scoring -> draft preparation sequentially, skips suppressed accounts, and records per-account results. Research failure preserves that account and skips draft regeneration instead of silently using stale evidence. Jobs continue while the local server runs, even with the browser closed. The UI refreshes active job status every three seconds; that local refresh does not re-fetch external websites. Server restart marks unfinished jobs interrupted, with no automatic retry. Cancel stops between bounded steps; an in-flight request or local inference can finish first. Workspace writes are rejected while a batch is active to avoid racing edits against generated drafts.

Workspace backup downloads local account data, playbook, experiments, recent run traces and recent job history as JSON. Treat it as private prospect data; do not upload it to GitHub. This version exports backups but does not yet import/restore them. For full SQLite recovery, stop the server and back up the database file.

## Distribution experiments

The Experiments board stores marketing hypotheses, channel, content draft, manual launch state, manually entered impressions/responses/conversions and learning notes. Response rate = responses / impressions; conversion rate = conversions / responses. Zero denominators show no data. Counts must satisfy conversions <= responses <= impressions. Marking launched requires confirmation that you took the action outside the app. No publishing, tracking pixel or analytics service is connected. This is a simple funnel record, not unique-user attribution.

## Product direction

The first wedge is a trustworthy account-to-draft loop. Further work: deeper source retrieval, better evaluated AI, configurable workflow nodes, explicit provider cost controls, CRM adapters, consent-aware approved delivery and outcome feedback. Those are future work, not working features today.

Category references, checked October 20, 2026: [Clay workflows](https://www.clay.com/workflows), [Clay developer workflow guide](https://developers.clay.com/use-cases/run-gtm-workflows). These were used for category understanding only; no Clay source code, assets or branding were copied.
