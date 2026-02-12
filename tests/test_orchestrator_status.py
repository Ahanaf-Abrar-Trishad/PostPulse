from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.core.config import load_settings, reset_settings_cache
from app.db.repository import Repository
from app.db.session import get_session_factory, init_db, session_scope
from app.orchestrator import Orchestrator
from app.scrapers.base import CompanyCandidate


def _build_orchestrator(config_path: Path, db_file: Path) -> Orchestrator:
    reset_settings_cache()
    settings = load_settings(str(config_path))
    settings.secrets.database_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    settings.config.notifications.webhook_enabled = False
    session_factory = get_session_factory(settings)
    init_db(settings)
    return Orchestrator(settings=settings, session_factory=session_factory)


def test_scrape_marks_missing_platform_ids_as_failed(test_config_path: Path, tmp_path: Path):
    orch = _build_orchestrator(test_config_path, tmp_path / "missing_ids.db")
    company = orch.settings.config.companies[0]
    company.linkedin_company_id = None
    company.facebook_page_id = None
    orch.bootstrap_companies()

    result = orch.scrape_posts(platform="all")
    assert result["status"] == "failed"
    assert result["posts_processed"] == 0
    assert result["skipped_missing_platform_id"] >= 1


def test_promote_candidate_respects_monitor_cap(test_config_path: Path, tmp_path: Path):
    orch = _build_orchestrator(test_config_path, tmp_path / "cap.db")
    orch.settings.config.discovery.max_monitored_companies = 1
    orch.bootstrap_companies()

    with session_scope(orch.session_factory) as session:
        repo = Repository(session)
        candidate_id = repo.upsert_company_candidate(
            CompanyCandidate(
                platform="linkedin",
                name="Another Co",
                profile_url="https://www.linkedin.com/company/another/",
                platform_company_id="778899",
                confidence=0.8,
                source_keyword="erp",
                metadata={"source": "test"},
            )
        )

    response = orch.promote_candidate(UUID(str(candidate_id)))
    assert response["status"] == "ignored"
    assert response["ignored_due_to_monitor_limit"] == 1


def test_discover_payload_contains_monitoring_fields(test_config_path: Path, tmp_path: Path, monkeypatch):
    orch = _build_orchestrator(test_config_path, tmp_path / "discover.db")
    monkeypatch.setattr(orch.linkedin_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.facebook_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.linkedin_collector, "discover_companies", lambda _: [])
    monkeypatch.setattr(orch.facebook_collector, "discover_companies", lambda _: [])

    response = orch.discover_candidates(keywords_override=["erp"])
    assert "candidates_promoted" in response
    assert "ignored_due_to_monitor_limit" in response
