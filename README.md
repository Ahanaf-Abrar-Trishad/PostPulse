# SocialIntel Pipeline (Local v1)

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

7. Run daily pipeline:

```bash
python -m app.main run-daily
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

## License

Internal/private use unless you add a formal open-source license file.

## Additional Docs

- `SETUP_GUIDE.md`
- `API_DOCUMENTATION.md`
- `DEPLOYMENT_GUIDE.md`
