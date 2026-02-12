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
    refreshed.config.companies = settings.config.companies

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
    monkeypatch.setattr(orch.fallback_collector, "fetch_posts", lambda *args, **kwargs: [])

    scrape = orch.scrape_posts(platform="all")
    assert scrape["posts_processed"] >= 1
    assert scrape["skipped_missing_platform_id"] == 0

    analysis = orch.analyze(window_days=90)
    assert analysis["status"] == "success"

    generated = orch.generate_content(count=2, platforms=["linkedin", "facebook"])
    assert generated["count"] == 2
