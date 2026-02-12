# PostPulse (Local v1.2)

Compliant social intelligence pipeline for collecting public company posts from LinkedIn and Facebook, analyzing engagement patterns, and generating original B2B social content.

## Legal and Compliance Disclaimer

You are responsible for ensuring your use complies with each platform's Terms of Service, API policies, and local laws.  
This project is designed for public content and authorized API access only. It does **not** support scraping private or restricted content, credential abuse, or anti-detection bypass techniques.

## Features

- API-first collectors for LinkedIn and Facebook.
- Optional Playwright fallback for public pages only (robots.txt-aware).
- PostgreSQL storage with normalized post schema and idempotent upserts.
- Analytics pipeline:
  - high-performing pattern detection
  - posting time windows
  - hashtag and CTA effectiveness
  - topic extraction (TF-IDF + NMF)
- Content generation (OpenAI + rule-based fallback) with similarity guard.
- Automation via APScheduler.
- CLI and minimal local FastAPI UI.
- CSV/JSON/XLSX export.
- Webhook notifications and structured logs.

## What's New in v1.2

- Hybrid candidate promotion in discovery:
  - auto-promote only when confidence and platform ID thresholds are met
  - keep manual approval and manual promotion commands
- Discovery payload correctness:
  - `new_candidates`
  - `updated_candidates`
  - `candidates_promoted`
  - `ignored_due_to_monitor_limit`
- Missing platform ID handling:
  - optional fallback collection from public profile URLs when enabled
  - new scrape counter: `fallback_without_platform_id_used`
- Fallback timestamp safety:
  - cards without parseable publish dates are skipped (no fabricated `now()` timestamp)
- Facebook date parsing hardening:
  - supports common Graph `created_time` variants and safely skips invalid rows

## Architecture

```text
[CLI (Typer)] ----\
[Web UI (FastAPI)] ---> [Orchestrator] ---> [Scheduler (APScheduler)]
                               |                  |
                               v                  v
                      [Collectors Layer] --> [Run Queue/Jobs]
                    (LinkedIn API, FB API,
                     Playwright fallback)
                               |
                               v
                        [Normalizer/Cleaner]
                               |
                               v
                    [PostgreSQL (SQLAlchemy)]
                               |
                               v
          [Analyzer (pandas/sklearn)] ---> [Insights JSON + Tables]
                               |
                               v
               [Generator (OpenAI + Similarity Guard)]
                               |
                               v
                    [Exports + Webhook Notifications]
```

## Quick Start (30 min)

1. Install Python 3.11+ and PostgreSQL 16.
2. Create and activate virtualenv.
3. Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

4. Configure environment:

```bash
cp .env.example .env
cp config/config.yaml.example config/config.yaml
```

Windows PowerShell alternative:

```powershell
Copy-Item .env.example .env
Copy-Item config/config.yaml.example config/config.yaml
```

5. Set required values in `.env`:
   - `DATABASE_URL`
   - `LINKEDIN_ACCESS_TOKEN`
   - `FACEBOOK_ACCESS_TOKEN`
   - `OPENAI_API_KEY`

Optional token refresh fields:
- `LINKEDIN_REFRESH_TOKEN` (+ client id/secret)
- `FACEBOOK_REFRESH_TOKEN` (+ app id/secret)

6. Initialize DB and seed configured companies:

```bash
python -m app.main init-db
```

Company config supports optional platform IDs for direct scraping:
- `linkedin_company_id`
- `facebook_page_id`

Discovery config supports hybrid auto-promotion:
- `auto_promote_enabled`
- `auto_promote_min_confidence`

Scrape config supports fallback collection without platform IDs:
- `allow_fallback_without_platform_id`

7. Run daily pipeline:

```bash
python -m app.main run-daily
```

Optional first-run candidate workflow:

```bash
python -m app.main discover --keywords-file config/keywords.txt
python -m app.main candidates-list --platform all
python -m app.main candidates-activate --candidate-id <uuid>
python -m app.main candidates-promote --candidate-id <uuid>
```

## CLI Commands

- `socialintel init-db`
- `socialintel discover --keywords-file config/keywords.txt`
- `socialintel scrape --platform all --since 2025-11-14`
- `socialintel analyze --window-days 90`
- `socialintel generate --count 12 --platform all`
- `socialintel export --format csv --out exports/`
- `socialintel candidates-list --platform all`
- `socialintel candidates-activate --candidate-id <uuid>`
- `socialintel candidates-promote --candidate-id <uuid>`
- `socialintel run-daily`
- `socialintel schedule`
- `socialintel ui --host 127.0.0.1 --port 8080`

If `socialintel` is not available, use `python -m app.main`.

Candidate lifecycle semantics:
- `candidates-activate` marks candidate as reviewed/approved only.
- `candidates-promote` creates/updates scrape targets (companies/platform accounts).

Discover output semantics:
- `new_candidates`: first-time candidate records created.
- `updated_candidates`: existing candidates updated.
- `candidates_promoted`: candidates promoted to active scrape targets.
- `ignored_due_to_monitor_limit`: promotion attempts blocked by `max_monitored_companies`.

Scrape output semantics:
- `fallback_without_platform_id_used`: missing-ID accounts scraped via public fallback.
- `skipped_missing_platform_id`: missing-ID accounts skipped due to policy/config/insufficient URL.
- `fallback_skipped_no_date`: fallback cards skipped because date was missing/unparseable.
- `fallback_cards_seen`: diagnostic count of fallback cards scanned.

## Web UI

Start:

```bash
python -m app.main ui --host 127.0.0.1 --port 8080
```

Routes:

- `GET /` latest run states
- `GET /runs` run history
- `GET /logs` paginated logs
- `GET /config` config snapshot
- `POST /config` editable config update
- `POST /trigger/{job}` job trigger (`discover|scrape|analyze|generate`)

## Project Structure

```text
app/
  analyzer/service.py
  core/{config,logging,rate_limit}.py
  db/{models,repository,session}.py
  generator/service.py
  scrapers/{base,linkedin,facebook,fallback_playwright}.py
  scheduler/service.py
  ui/server.py
  orchestrator.py
  main.py
config/
  config.yaml
  config.yaml.example
  keywords.txt
tests/
```

## Troubleshooting

- `Missing *_ACCESS_TOKEN`: set token values in `.env`.
- `relation does not exist`: run `init-db` after DB is reachable.
- Playwright issues: run `playwright install chromium`.
- Empty discovery results: token may not have required API permissions; use curated company list in config.
- `skipped_missing_platform_id > 0` in scrape output: set `linkedin_company_id` / `facebook_page_id` in config or promote discovered candidates.
- `fallback_without_platform_id_used`: number of missing-ID accounts collected through public fallback.
- `status=partial_success`: some posts processed, but at least one failure or skip occurred.
- `status=failed`: no posts processed and at least one failure or skip occurred.

## License

Internal/private use unless you add a formal open-source license file.

## Additional Docs

- `SETUP_GUIDE.md`
- `API_DOCUMENTATION.md`
- `DEPLOYMENT_GUIDE.md`
