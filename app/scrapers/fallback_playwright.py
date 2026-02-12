from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import PlatformLimiter, execute_with_retry
from app.scrapers.base import (
    CompanyRef,
    NormalizedPost,
    RawPost,
    extract_cta_text,
    extract_hashtags,
    extract_links,
    infer_post_structure,
    metrics_provenance,
)

logger = get_logger(__name__)

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class PlaywrightFallbackCollector:
    def __init__(self, settings: Settings, limiter: PlatformLimiter) -> None:
        self.settings = settings
        self.limiter = limiter
        self.user_agent = settings.config.scrape.user_agent
        self.timeout_ms = settings.config.scrape.navigation_timeout_seconds * 1000
        self.last_skipped_no_date = 0
        self.last_cards_seen = 0

    def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            parser.set_url(robots_url)
            parser.read()
            return parser.can_fetch(self.user_agent, url)
        except Exception:  # noqa: BLE001
            logger.warning("Could not evaluate robots.txt for %s; denying fallback crawl", url)
            return False

    def fetch_posts(self, company: CompanyRef, since: datetime, until: datetime) -> list[RawPost]:
        self.last_skipped_no_date = 0
        self.last_cards_seen = 0
        if not self.allowed_by_robots(company.profile_url):
            logger.warning("Robots denied fallback for %s", company.profile_url)
            return []

        def operation() -> list[RawPost]:
            return self._fetch_posts_internal(company, since, until)

        try:
            return execute_with_retry(
                operation=operation,
                limiter=self.limiter,
                attempts=self.settings.config.rate_limit.fallback.retry_max_attempts,
                base_seconds=self.settings.config.rate_limit.fallback.retry_base_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Fallback fetch failed company=%s error=%s", company.name, exc)
            return []

    def _fetch_posts_internal(self, company: CompanyRef, since: datetime, until: datetime) -> list[RawPost]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            try:
                page.goto(company.profile_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(1500)
                html = page.content()
            except PlaywrightTimeoutError:
                logger.warning("Fallback navigation timeout company=%s", company.name)
                browser.close()
                return []
            browser.close()
        return self._parse_public_html(company, html, since, until)

    def _parse_public_html(
        self, company: CompanyRef, html: str, since: datetime, until: datetime
    ) -> list[RawPost]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article, div.feed-shared-update-v2, div[data-pagelet^='FeedUnit']")
        self.last_cards_seen = len(cards)
        posts: list[RawPost] = []
        skipped_no_date = 0
        for idx, node in enumerate(cards):
            text = " ".join(chunk.strip() for chunk in node.stripped_strings)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            time_tag = node.find("time")
            date_text = (
                node.get("datetime")
                or (time_tag.get("datetime") if time_tag else None)
                or " ".join(node.stripped_strings)
            )
            published_at = self._extract_date(date_text)
            if published_at is None:
                skipped_no_date += 1
                continue
            if published_at < since or published_at > until:
                continue
            media_type = self._infer_media_type(node)
            posts.append(
                RawPost(
                    post_id=f"fallback-{company.platform}-{idx}-{int(published_at.timestamp())}",
                    text=text,
                    published_at=published_at,
                    media_type=media_type,
                    metrics={"likes": None, "comments": None, "shares": None, "views": None},
                    metadata={"source": "playwright_fallback"},
                )
            )
        self.last_skipped_no_date = skipped_no_date
        return posts

    @staticmethod
    def _extract_date(text: str) -> datetime | None:
        match = DATE_PATTERN.search(text or "")
        if not match:
            return None
        try:
            return datetime.fromisoformat(match.group(0)).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _infer_media_type(node: Any) -> str:
        html = str(node).lower()
        has_image = "<img" in html
        has_video = "<video" in html
        has_pdf = ".pdf" in html
        types = [has_image, has_video, has_pdf]
        if sum(1 for value in types if value) > 1:
            return "mixed"
        if has_video:
            return "video"
        if has_image:
            return "image"
        if has_pdf:
            return "document"
        return "text"

    @staticmethod
    def normalize(raw: RawPost, company: CompanyRef) -> NormalizedPost:
        text = raw.text or ""
        return NormalizedPost(
            platform=company.platform,
            platform_post_id=raw.post_id,
            company_id=company.id,
            company_name=company.name,
            company_profile_url=company.profile_url,
            post_text=text,
            published_at=raw.published_at,
            media_type=raw.media_type,
            hashtags=extract_hashtags(text),
            links=extract_links(text),
            cta_text=extract_cta_text(text),
            post_structure=infer_post_structure(text),
            metrics=raw.metrics,
            metrics_provenance=metrics_provenance(raw.metrics, source="scrape"),
        )
