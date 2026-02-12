from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import load_settings, reset_settings_cache


@pytest.fixture()
def test_config_path(tmp_path: Path) -> Path:
    content = """
environment: local
discovery:
  keywords: ["erp implementation"]
  max_candidates_per_keyword: 10
  max_monitored_companies: 20
companies:
  - name: Test Co
    website: https://example.com
    linkedin_url: https://www.linkedin.com/company/testco/
    facebook_url: https://www.facebook.com/testco
    active: true
scrape:
  backfill_days: 90
  lookback_hours_on_incremental: 2
  default_platforms: [linkedin, facebook]
  include_playwright_fallback: true
  user_agent: test-agent
  navigation_timeout_seconds: 30
rate_limit:
  linkedin:
    requests_per_minute: 60
    jitter_min_seconds: 0
    jitter_max_seconds: 0
    retry_max_attempts: 2
    retry_base_seconds: 0.01
    circuit_breaker_threshold: 5
    circuit_breaker_cooldown_seconds: 30
  facebook:
    requests_per_minute: 60
    jitter_min_seconds: 0
    jitter_max_seconds: 0
    retry_max_attempts: 2
    retry_base_seconds: 0.01
    circuit_breaker_threshold: 5
    circuit_breaker_cooldown_seconds: 30
  fallback:
    requests_per_minute: 30
    jitter_min_seconds: 0
    jitter_max_seconds: 0
    retry_max_attempts: 2
    retry_base_seconds: 0.01
    circuit_breaker_threshold: 5
    circuit_breaker_cooldown_seconds: 30
generation:
  default_count: 12
  min_themes: 4
  max_similarity_threshold: 0.82
  default_language: en
  style: B2B thought leadership
  linkedin_ratio: 0.5
scheduler:
  timezone: UTC
  discover_cron: "0 1 * * *"
  scrape_cron: "0 2 * * *"
  analyze_cron: "0 3 * * *"
  generate_cron: "30 3 * * *"
export:
  default_formats: [csv, json, xlsx]
  output_dir: exports
web_ui:
  host: 127.0.0.1
  port: 8080
  editable_config_path: config/config.yaml
notifications:
  webhook_enabled: false
  webhook_timeout_seconds: 5
"""
    path = tmp_path / "config.yaml"
    path.write_text(content.strip(), encoding="utf-8")
    return path


@pytest.fixture()
def settings(test_config_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "token")
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "token")
    reset_settings_cache()
    result = load_settings(str(test_config_path))
    yield result
    reset_settings_cache()
