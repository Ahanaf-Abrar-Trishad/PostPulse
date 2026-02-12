# SETUP_GUIDE.md

## 1) Environment Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Git

Optional:
- Docker + Docker Compose

### Create virtual environment

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate
```

### Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

## 2) Configuration

### Copy templates

```bash
cp .env.example .env
cp config/config.yaml.example config/config.yaml
```

### Update `.env`

Required:
- `DATABASE_URL`
- `LINKEDIN_ACCESS_TOKEN`
- `FACEBOOK_ACCESS_TOKEN`
- `OPENAI_API_KEY` (optional if using rule-based generation only)

Optional refresh support:
- `LINKEDIN_REFRESH_TOKEN`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`
- `FACEBOOK_REFRESH_TOKEN`, `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`

### Update `config/config.yaml`

- Add keywords under `discovery.keywords`.
- Add target companies under `companies`.
- Optionally set `linkedin_company_id` and `facebook_page_id` per company for direct scraping without discovery promotion.
- Optional hybrid discovery promotion controls:
  - `discovery.auto_promote_enabled`
  - `discovery.auto_promote_min_confidence`
- Optional scrape control:
  - `scrape.allow_fallback_without_platform_id`
- Adjust scheduling and rate limits if needed.

### Candidate lifecycle commands

```bash
python -m app.main candidates-list --platform all
python -m app.main candidates-activate --candidate-id <uuid>
python -m app.main candidates-promote --candidate-id <uuid>
```

`candidates-activate` is review-only.  
`candidates-promote` makes a candidate an actual scrape target.

## 3) Database Initialization

```bash
python -m app.main init-db
```

This creates tables and seeds `companies` + `company_platform_accounts` from config.

## 4) First Run Walkthrough

```bash
python -m app.main discover --keywords-file config/keywords.txt
python -m app.main scrape --platform all
python -m app.main analyze --window-days 90
python -m app.main generate --count 12 --platform all
python -m app.main export --format csv --out exports
```

Or run full workflow:

```bash
python -m app.main run-daily
```

## 5) Local UI

```bash
python -m app.main ui --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`.

## 6) Scheduler

```bash
python -m app.main schedule
```

Default cron schedule (UTC):
- Discover: 01:00
- Scrape: 02:00
- Analyze: 03:00
- Generate: 03:30

## 7) Docker Setup (Optional)

```bash
docker compose up -d db
docker compose run --rm app python -m app.main init-db
docker compose run --rm app python -m app.main run-daily
```

## 8) Cloud Notes (Optional)

Local v1 is primary target. For cloud:
- Run app in container.
- Use managed PostgreSQL.
- Use managed scheduler (e.g., Cloud Scheduler, EventBridge, cronjob).
- Route logs to cloud logging.

## 9) Common Issues

- Authentication/permission errors:
  - verify token scopes and app approvals.
- Empty analytics:
  - check scrape output and company activation.
- Fallback scrape blocked:
  - page may disallow crawling in `robots.txt` or require login.
