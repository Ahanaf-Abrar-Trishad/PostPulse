from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.core.config import load_settings, reset_settings_cache
from app.db.repository import Repository
from app.db.session import get_session_factory, init_db, session_scope
from app.orchestrator import Orchestrator
from app.scrapers.base import CompanyCandidate as CandidateDTO
from app.scrapers.base import CompanyRef, RawPost


def _build_orchestrator(config_path: Path, db_file: Path) -> Orchestrator:
    reset_settings_cache()
    settings = load_settings(str(config_path))
    settings.secrets.database_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    settings.config.notifications.webhook_enabled = False
    session_factory = get_session_factory(settings)
    init_db(settings)
    return Orchestrator(settings=settings, session_factory=session_factory)


def test_discover_tracks_new_updated_and_auto_promote(test_config_path: Path, tmp_path: Path, monkeypatch):
    orch = _build_orchestrator(test_config_path, tmp_path / "discover_flow.db")
    orch.settings.config.discovery.auto_promote_enabled = True
    orch.settings.config.discovery.auto_promote_min_confidence = 0.85
    orch.settings.config.discovery.max_monitored_companies = 20
    orch.bootstrap_companies()

    candidate = CandidateDTO(
        platform="linkedin",
        name="New ERP Co",
        profile_url="https://www.linkedin.com/company/new-erp-co/",
        platform_company_id="100200",
        confidence=0.9,
        source_keyword="erp",
        metadata={"source": "test"},
    )

    monkeypatch.setattr(orch.linkedin_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.facebook_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.linkedin_collector, "discover_companies", lambda _: [candidate, candidate])
    monkeypatch.setattr(orch.facebook_collector, "discover_companies", lambda _: [])

    result = orch.discover_candidates(keywords_override=["erp"])
    assert result["new_candidates"] == 1
    assert result["updated_candidates"] == 1
    assert result["candidates_promoted"] == 1
    assert result["ignored_due_to_monitor_limit"] == 0


def test_discover_cap_blocks_auto_promotion(test_config_path: Path, tmp_path: Path, monkeypatch):
    orch = _build_orchestrator(test_config_path, tmp_path / "discover_cap.db")
    orch.settings.config.discovery.auto_promote_enabled = True
    orch.settings.config.discovery.auto_promote_min_confidence = 0.85
    orch.settings.config.discovery.max_monitored_companies = 1
    orch.bootstrap_companies()

    candidate = CandidateDTO(
        platform="linkedin",
        name="Blocked Co",
        profile_url="https://www.linkedin.com/company/blocked-co/",
        platform_company_id="9988",
        confidence=0.95,
        source_keyword="erp",
        metadata={"source": "test"},
    )
    monkeypatch.setattr(orch.linkedin_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.facebook_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.linkedin_collector, "discover_companies", lambda _: [candidate])
    monkeypatch.setattr(orch.facebook_collector, "discover_companies", lambda _: [])

    result = orch.discover_candidates(keywords_override=["erp"])
    assert result["new_candidates"] == 1
    assert result["updated_candidates"] == 0
    assert result["candidates_promoted"] == 0
    assert result["ignored_due_to_monitor_limit"] == 1


def test_activate_candidate_is_approval_only(test_config_path: Path, tmp_path: Path):
    orch = _build_orchestrator(test_config_path, tmp_path / "activate_only.db")
    orch.bootstrap_companies()
    with session_scope(orch.session_factory) as session:
        repo = Repository(session)
        candidate_id, _ = repo.upsert_company_candidate(
            CandidateDTO(
                platform="linkedin",
                name="Review Co",
                profile_url="https://www.linkedin.com/company/review-co/",
                platform_company_id="5544",
                confidence=0.7,
                source_keyword="erp",
                metadata={"source": "test"},
            )
        )
        active_companies_before = repo.count_active_companies()

    response = orch.activate_candidate(UUID(str(candidate_id)))
    assert response["status"] in {"activated", "already_active"}
    assert response["note"] == "approved_only_not_promoted"

    with session_scope(orch.session_factory) as session:
        repo = Repository(session)
        candidate = repo.get_candidate(UUID(str(candidate_id)))
        assert candidate is not None and candidate.active is True
        assert repo.count_active_companies() == active_companies_before


def test_scrape_missing_id_uses_fallback_when_enabled(test_config_path: Path, tmp_path: Path, monkeypatch):
    orch = _build_orchestrator(test_config_path, tmp_path / "fallback_without_id.db")
    company = orch.settings.config.companies[0]
    company.linkedin_company_id = None
    company.facebook_page_id = None
    orch.settings.config.scrape.allow_fallback_without_platform_id = True
    orch.bootstrap_companies()

    def fake_fallback(company_ref: CompanyRef, since: datetime, until: datetime):
        orch.fallback_collector.last_skipped_no_date = 0
        orch.fallback_collector.last_cards_seen = 1
        return [
            RawPost(
                post_id=f"fallback-{company_ref.platform}-1",
                text="Public fallback post #ERP",
                published_at=datetime.now(timezone.utc),
                media_type="text",
                metrics={"likes": None, "comments": None, "shares": None, "views": None},
                metadata={"source": "test"},
            )
        ]

    monkeypatch.setattr(orch.fallback_collector, "fetch_posts", fake_fallback)
    monkeypatch.setattr(orch.linkedin_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.facebook_collector, "authenticate", lambda: None)

    result = orch.scrape_posts(platform="all")
    assert result["posts_processed"] >= 1
    assert result["fallback_without_platform_id_used"] >= 1
    assert result["skipped_missing_platform_id"] == 0
    assert result["status"] in {"success", "partial_success"}


def test_scrape_missing_id_strict_skip(test_config_path: Path, tmp_path: Path):
    orch = _build_orchestrator(test_config_path, tmp_path / "strict_skip.db")
    company = orch.settings.config.companies[0]
    company.linkedin_company_id = None
    company.facebook_page_id = None
    orch.settings.config.scrape.allow_fallback_without_platform_id = False
    orch.bootstrap_companies()

    result = orch.scrape_posts(platform="all")
    assert result["posts_processed"] == 0
    assert result["fallback_without_platform_id_used"] == 0
    assert result["skipped_missing_platform_id"] >= 1
    assert result["status"] == "failed"
