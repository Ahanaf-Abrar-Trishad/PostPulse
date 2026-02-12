from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import PlatformLimiter, execute_with_retry
from app.scrapers.base import (
    BaseCollector,
    CompanyCandidate,
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


class FacebookCollector(BaseCollector):
    platform = "facebook"

    def __init__(self, settings: Settings, limiter: PlatformLimiter) -> None:
        self.settings = settings
        self.limiter = limiter
        self.base_url = "https://graph.facebook.com/v19.0"
        self.token = settings.secrets.facebook_access_token
        self.client = httpx.Client(timeout=30.0)

    def authenticate(self) -> None:
        if self.token:
            return
        refresh_token = self.settings.secrets.facebook_refresh_token
        if refresh_token:
            self._refresh_access_token(refresh_token)
        if not self.token:
            raise RuntimeError("Missing FACEBOOK_ACCESS_TOKEN and token refresh failed")

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = params.copy() if params else {}
        payload["access_token"] = self.token
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        def operation() -> dict[str, Any]:
            response = self.client.get(url, params=payload)
            response.raise_for_status()
            return response.json()

        return execute_with_retry(
            operation=operation,
            limiter=self.limiter,
            attempts=self.settings.config.rate_limit.facebook.retry_max_attempts,
            base_seconds=self.settings.config.rate_limit.facebook.retry_base_seconds,
        )

    def _refresh_access_token(self, refresh_token: str) -> None:
        app_id = self.settings.secrets.facebook_app_id
        app_secret = self.settings.secrets.facebook_app_secret
        if not app_id or not app_secret:
            return

        def operation() -> dict[str, Any]:
            response = self.client.get(
                f"{self.base_url}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": refresh_token,
                },
            )
            response.raise_for_status()
            return response.json()

        try:
            payload = execute_with_retry(
                operation=operation,
                limiter=self.limiter,
                attempts=self.settings.config.rate_limit.facebook.retry_max_attempts,
                base_seconds=self.settings.config.rate_limit.facebook.retry_base_seconds,
            )
            token = payload.get("access_token")
            if token:
                self.token = token
        except Exception as exc:  # noqa: BLE001
            logger.warning("Facebook token refresh failed: %s", exc)

    def discover_companies(self, keywords: list[str]) -> list[CompanyCandidate]:
        candidates: list[CompanyCandidate] = []
        for keyword in keywords:
            try:
                payload = self._get(
                    "search",
                    {
                        "type": "page",
                        "q": keyword,
                        "fields": "id,name,link,category",
                        "limit": self.settings.config.discovery.max_candidates_per_keyword,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Facebook discovery failed for keyword=%s error=%s", keyword, exc)
                continue

            for item in payload.get("data", []):
                candidates.append(
                    CompanyCandidate(
                        platform="facebook",
                        name=item.get("name", ""),
                        profile_url=item.get("link", ""),
                        platform_company_id=item.get("id"),
                        confidence=0.8,
                        source_keyword=keyword,
                        metadata={"category": item.get("category")},
                    )
                )
        return candidates

    def fetch_posts(
        self, company: CompanyRef, since: datetime, until: datetime
    ) -> list[RawPost]:
        if not company.platform_company_id:
            logger.warning("Skipping Facebook company with missing platform_company_id: %s", company.name)
            return []
        try:
            payload = self._get(
                f"{company.platform_company_id}/posts",
                {
                    "fields": ",".join(
                        [
                            "id",
                            "message",
                            "created_time",
                            "permalink_url",
                            "shares",
                            "attachments{media_type,type,url}",
                            "reactions.summary(true)",
                            "comments.summary(true)",
                        ]
                    ),
                    "limit": 100,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Facebook fetch failed for %s: %s", company.name, exc)
            return []

        records: list[RawPost] = []
        for item in payload.get("data", []):
            created_raw = item.get("created_time")
            if not created_raw:
                continue
            published_at = self._parse_created_time(created_raw)
            if published_at is None:
                logger.warning(
                    "Skipping Facebook post with unparseable created_time. company=%s post_id=%s created_time=%s",
                    company.name,
                    item.get("id"),
                    created_raw,
                )
                continue
            if published_at < since or published_at > until:
                continue
            text = item.get("message", "")
            attachments = item.get("attachments", {}).get("data", [])
            media_type = self._infer_media_type(attachments)
            metrics = {
                "likes": (item.get("reactions") or {}).get("summary", {}).get("total_count"),
                "comments": (item.get("comments") or {}).get("summary", {}).get("total_count"),
                "shares": (item.get("shares") or {}).get("count"),
                "views": None,
            }
            records.append(
                RawPost(
                    post_id=item.get("id", ""),
                    text=text,
                    published_at=published_at,
                    media_type=media_type,
                    metrics=metrics,
                    metadata=item,
                )
            )
        return records

    def normalize(self, raw: RawPost, company: CompanyRef) -> NormalizedPost:
        text = raw.text or ""
        return NormalizedPost(
            platform="facebook",
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
            metrics_provenance=metrics_provenance(raw.metrics, source="api"),
        )

    @staticmethod
    def _infer_media_type(attachments: list[dict[str, Any]]) -> str:
        if not attachments:
            return "text"
        kinds = set()
        for item in attachments:
            media_type = (item.get("media_type") or item.get("type") or "").lower()
            if "photo" in media_type or "image" in media_type:
                kinds.add("image")
            elif "video" in media_type:
                kinds.add("video")
            elif "album" in media_type:
                kinds.add("carousel")
            elif "file" in media_type or "document" in media_type:
                kinds.add("document")
            else:
                kinds.add("unknown")
        if len(kinds) == 1:
            return kinds.pop()
        return "mixed"

    @staticmethod
    def _parse_created_time(created_raw: str) -> datetime | None:
        try:
            return datetime.fromisoformat(created_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            return datetime.strptime(created_raw, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
        except ValueError:
            return None
