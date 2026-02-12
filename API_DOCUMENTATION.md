# API_DOCUMENTATION.md

## Module Architecture

- `app/main.py`: Typer CLI entrypoint.
- `app/orchestrator.py`: workflow coordinator for discover/scrape/analyze/generate/export.
- `app/scrapers/*`: platform collectors and fallback parser.
- `app/db/*`: SQLAlchemy models, session factory, repository.
- `app/analyzer/service.py`: statistical + topical analysis.
- `app/generator/service.py`: AI/rule-based post generation.
- `app/scheduler/service.py`: APScheduler cron orchestration.
- `app/ui/server.py`: minimal FastAPI local UI.

## Core Interfaces

### `BaseCollector` (`app/scrapers/base.py`)

```python
class BaseCollector(Protocol):
    platform: Literal["linkedin", "facebook"]
    def authenticate(self) -> None: ...
    def discover_companies(self, keywords: list[str]) -> list[CompanyCandidate]: ...
    def fetch_posts(self, company: CompanyRef, since: datetime, until: datetime) -> list[RawPost]: ...
    def normalize(self, raw: RawPost, company: CompanyRef) -> NormalizedPost: ...
```

### `NormalizedPost`

Canonical post model for DB persistence and analytics.

Fields include:
- content, datetime, company identity
- media type, hashtags, links, CTA
- engagement metrics + provenance (`api|scrape|unavailable`)

## Repository API (`app/db/repository.py`)

Key methods:
- `sync_companies_from_config(...)`
- `upsert_company_candidate(...) -> tuple[candidate_id, created_new_record]`
- `list_candidates(platform, active_only, limit)`
- `activate_candidate(candidate_id)`
- `promote_candidate_to_company(candidate_id)`
- `is_candidate_auto_promotable(candidate, min_confidence)`
- `count_active_companies()`
- `get_active_company_refs(...)`
- `create_scrape_run(...)`, `finish_scrape_run(...)`
- `upsert_post(...)`
- `create_analysis_run(...)`, `finish_analysis_run(...)`, `add_analysis_insight(...)`
- `save_generated_post(...)`
- export helpers (`posts_to_dataframe`, `generated_posts_to_dataframe`)

## Orchestrator API (`app/orchestrator.py`)

- `bootstrap_companies()`
- `discover_candidates(keywords_override=None)`
- `scrape_posts(platform="all", since=None, until=None)`
- `list_candidates(platform="all", active_only=False)`
- `activate_candidate(candidate_id)`
- `promote_candidate(candidate_id)`
- `analyze(window_days=90)`
- `generate_content(count=12, platforms=["linkedin","facebook"])`
- `export_data(format_name, out_dir=None)`
- `run_daily()`

## CLI API (`app/main.py`)

- `init-db`
- `discover`
- `scrape`
- `analyze`
- `generate`
- `export`
- `candidates-list`
- `candidates-activate`
- `candidates-promote`
- `run-daily`
- `schedule`
- `ui`

Scrape payload now includes:
- `skipped_missing_platform_id`
- `fallback_skipped_no_date`
- `fallback_without_platform_id_used`
- `fallback_cards_seen`

Discovery payload now includes:
- `new_candidates`
- `updated_candidates`
- `candidates_promoted`
- `ignored_due_to_monitor_limit`

Activation vs promotion:
- `activate_candidate`: review/approval marker only.
- `promote_candidate`: creates/updates company scrape target and platform account.

## Web API (`app/ui/server.py`)

- `GET /`
- `GET /runs`
- `GET /logs?page=1&page_size=100`
- `GET /config`
- `POST /config`
- `POST /trigger/{job}`

## Extension Guide

### Add a new platform

1. Create `app/scrapers/<platform>.py`.
2. Implement `BaseCollector` methods.
3. Register collector in `Orchestrator._collector_for`.
4. Add platform rate config in `config` schema.
5. Add platform-specific tests with mock payload fixtures.

### Add new analytics

1. Implement metric in `AnalyzerService.analyze_posts`.
2. Emit insight via `(insight_type, payload)` tuples.
3. Persist via repository `add_analysis_insight`.
4. Include summary reference in markdown/json output.

### Replace content model/provider

1. Update `ContentGeneratorService._generate_single`.
2. Keep `GeneratedContent` contract stable.
3. Preserve similarity and validation logic.

## Security Notes

- Secrets are loaded from `.env` via `pydantic-settings`.
- Do not store credentials in YAML or source code.
- Run with least privilege API tokens and rotate regularly.
- Collectors support optional token refresh when refresh credentials are configured.
