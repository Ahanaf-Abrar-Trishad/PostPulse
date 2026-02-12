from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.rate_limit import PlatformLimiter
from app.scrapers.base import CompanyRef
from app.scrapers.fallback_playwright import PlaywrightFallbackCollector


def test_parse_public_html(settings):
    collector = PlaywrightFallbackCollector(
        settings=settings,
        limiter=PlatformLimiter(settings.config.rate_limit.fallback),
    )
    html = open("tests/fixtures/public_company_feed.html", "r", encoding="utf-8").read()
    company = CompanyRef(
        id=uuid4(),
        name="Test Co",
        profile_url="https://example.com/company/test",
        platform="linkedin",
        platform_company_id=None,
    )
    since = datetime(2026, 2, 1, tzinfo=timezone.utc)
    until = datetime(2026, 2, 12, tzinfo=timezone.utc)
    posts = collector._parse_public_html(company, html, since, until)
    assert len(posts) == 2
    assert posts[0].media_type in {"image", "video", "text", "mixed"}
