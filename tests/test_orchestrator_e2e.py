from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.db.session import get_session_factory, init_db
from app.orchestrator import Orchestrator
from app.scrapers.base import CompanyRef, RawPost


def test_orchestrator_end_to_end(settings, monkeypatch, tmp_path: Path):
    db_file = tmp_path / "e2e.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_file.as_posix()}")

    from app.core.config import load_settings, reset_settings_cache

    reset_settings_cache()
    refreshed = load_settings("config/config.yaml")
    refreshed.config.notifications.webhook_enabled = False
    refreshed.config.companies = settings.config.companies + [
        settings.config.companies[0].model_copy(
            update={
                "name": "Fallback Co",
                "linkedin_url": "https://www.linkedin.com/company/fallback-co/",
                "facebook_url": "https://www.facebook.com/fallbackco",
                "linkedin_company_id": None,
                "facebook_page_id": None,
            }
        )
    ]

    session_factory = get_session_factory(refreshed)
    init_db(refreshed)
    orch = Orchestrator(refreshed, session_factory)
    orch.bootstrap_companies()

    def fake_fetch_posts(company: CompanyRef, since: datetime, until: datetime):
        return [
            RawPost(
                post_id=f"{company.platform}-1",
                text="ERP outcomes first. Book a demo. #ERP",
                published_at=datetime.now(timezone.utc),
                media_type="text",
                metrics={"likes": 12, "comments": 2, "shares": 1, "views": None},
                metadata={"mock": True},
            )
        ]

    monkeypatch.setattr(orch.linkedin_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.facebook_collector, "authenticate", lambda: None)
    monkeypatch.setattr(orch.linkedin_collector, "fetch_posts", fake_fetch_posts)
    monkeypatch.setattr(orch.facebook_collector, "fetch_posts", fake_fetch_posts)

    def fake_fallback(company: CompanyRef, since: datetime, until: datetime):
        orch.fallback_collector.last_skipped_no_date = 0
        orch.fallback_collector.last_cards_seen = 1
        return [
            RawPost(
                post_id=f"fallback-{company.platform}-1",
                text="Fallback post for missing ID #ERP",
                published_at=datetime.now(timezone.utc),
                media_type="text",
                metrics={"likes": None, "comments": None, "shares": None, "views": None},
                metadata={"mock": True},
            )
        ]

    monkeypatch.setattr(orch.fallback_collector, "fetch_posts", fake_fallback)

    scrape = orch.scrape_posts(platform="all")
    assert scrape["posts_processed"] >= 4
    assert scrape["skipped_missing_platform_id"] == 0
    assert scrape["fallback_without_platform_id_used"] >= 2

    analysis = orch.analyze(window_days=90)
    assert analysis["status"] == "success"

    generated = orch.generate_content(count=2, platforms=["linkedin", "facebook"])
    assert generated["count"] == 2
