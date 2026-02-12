from __future__ import annotations

from app.core.config import AppConfig


def test_config_loads(test_config_path):
    config = AppConfig.from_yaml(test_config_path)
    assert config.discovery.max_candidates_per_keyword == 10
    assert config.scrape.backfill_days == 90
    assert config.generation.default_count == 12
    assert config.discovery.auto_promote_enabled is True
    assert config.discovery.auto_promote_min_confidence == 0.85
    assert config.scrape.allow_fallback_without_platform_id is True
    assert config.companies[0].linkedin_company_id == "12345"
    assert config.companies[0].facebook_page_id == "67890"
