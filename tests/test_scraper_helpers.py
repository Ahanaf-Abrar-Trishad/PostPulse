from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.scrapers.base import (
    CompanyRef,
    RawPost,
    extract_cta_text,
    extract_hashtags,
    extract_links,
)
from app.scrapers.linkedin import LinkedInCollector
from app.core.rate_limit import PlatformLimiter


def test_extract_helpers():
    text = "Book a demo at https://example.com #ERP #Odoo #ERP"
    assert extract_hashtags(text) == ["erp", "odoo"]
    assert extract_links(text) == ["https://example.com"]
    assert extract_cta_text(text) == "book a demo"


def test_linkedin_normalize(settings):
    collector = LinkedInCollector(settings, PlatformLimiter(settings.config.rate_limit.linkedin))
    company = CompanyRef(
        id=uuid4(),
        name="Test Co",
        profile_url="https://www.linkedin.com/company/testco/",
        platform="linkedin",
        platform_company_id="123",
    )
    raw = RawPost(
        post_id="abc",
        text="We help SMEs modernize ERP. Learn more: https://example.com #ERP",
        published_at=datetime.now(timezone.utc),
        media_type="text",
        metrics={"likes": 10, "comments": 2, "shares": 1, "views": None},
        metadata={},
    )
    normalized = collector.normalize(raw, company)
    assert normalized.platform == "linkedin"
    assert normalized.company_name == "Test Co"
    assert "erp" in normalized.hashtags
    assert normalized.metrics_provenance["views"] == "unavailable"
