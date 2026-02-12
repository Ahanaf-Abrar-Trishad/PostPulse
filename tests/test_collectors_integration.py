from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import respx
from httpx import Response

from app.core.rate_limit import PlatformLimiter
from app.scrapers.base import CompanyRef
from app.scrapers.facebook import FacebookCollector
from app.scrapers.linkedin import LinkedInCollector


@respx.mock
def test_facebook_fetch_posts(settings):
    collector = FacebookCollector(settings, PlatformLimiter(settings.config.rate_limit.facebook))
    route = respx.get("https://graph.facebook.com/v19.0/111/posts").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "111_1",
                        "message": "Test message #ERP",
                        "created_time": "2026-02-10T10:00:00+0000",
                        "shares": {"count": 2},
                        "reactions": {"summary": {"total_count": 11}},
                        "comments": {"summary": {"total_count": 3}},
                        "attachments": {"data": [{"media_type": "photo"}]},
                    }
                ]
            },
        )
    )
    company = CompanyRef(
        id=uuid4(),
        name="Test Co",
        profile_url="https://facebook.com/testco",
        platform="facebook",
        platform_company_id="111",
    )
    posts = collector.fetch_posts(
        company=company,
        since=datetime(2026, 2, 1, tzinfo=timezone.utc),
        until=datetime(2026, 2, 12, tzinfo=timezone.utc),
    )
    assert route.called
    assert len(posts) == 1
    assert posts[0].metrics["likes"] == 11


@respx.mock
def test_linkedin_fetch_posts(settings):
    collector = LinkedInCollector(settings, PlatformLimiter(settings.config.rate_limit.linkedin))
    route = respx.get("https://api.linkedin.com/v2/ugcPosts").mock(
        return_value=Response(
            200,
            json={
                "elements": [
                    {
                        "id": "urn:li:ugcPost:1",
                        "created": {"time": 1739172000000},
                        "specificContent": {
                            "com.linkedin.ugc.ShareContent": {
                                "shareCommentary": {"text": "Sample #odoo post"},
                                "media": [],
                            }
                        },
                        "socialDetail": {
                            "totalSocialActivityCounts": {
                                "numLikes": 10,
                                "numComments": 1,
                                "numShares": 1,
                            }
                        },
                    }
                ]
            },
        )
    )
    company = CompanyRef(
        id=uuid4(),
        name="Test Co",
        profile_url="https://linkedin.com/company/testco",
        platform="linkedin",
        platform_company_id="1234",
    )
    posts = collector.fetch_posts(
        company=company,
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 12, 1, tzinfo=timezone.utc),
    )
    assert route.called
    assert len(posts) == 1
    assert posts[0].media_type == "text"
