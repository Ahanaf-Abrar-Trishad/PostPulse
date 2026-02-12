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


class LinkedInCollector(BaseCollector):
    platform = "linkedin"

    def __init__(self, settings: Settings, limiter: PlatformLimiter) -> None:
        self.settings = settings
        self.limiter = limiter
        self.base_url = "https://api.linkedin.com/v2"
        self.token = settings.secrets.linkedin_access_token
        self.client = httpx.Client(timeout=30.0)

    def authenticate(self) -> None:
        if self.token:
            return
        refresh_token = self.settings.secrets.linkedin_refresh_token
        if refresh_token:
            self._refresh_access_token(refresh_token)
        if not self.token:
            raise RuntimeError("Missing LINKEDIN_ACCESS_TOKEN and token refresh failed")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            response = self.client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()

        return execute_with_retry(
            operation=operation,
            limiter=self.limiter,
            attempts=self.settings.config.rate_limit.linkedin.retry_max_attempts,
            base_seconds=self.settings.config.rate_limit.linkedin.retry_base_seconds,
        )

    def _refresh_access_token(self, refresh_token: str) -> None:
        client_id = self.settings.secrets.linkedin_client_id
        client_secret = self.settings.secrets.linkedin_client_secret
        if not client_id or not client_secret:
            return

        def operation() -> dict[str, Any]:
            response = self.client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            response.raise_for_status()
            return response.json()

        try:
            payload = execute_with_retry(
                operation=operation,
                limiter=self.limiter,
                attempts=self.settings.config.rate_limit.linkedin.retry_max_attempts,
                base_seconds=self.settings.config.rate_limit.linkedin.retry_base_seconds,
            )
            token = payload.get("access_token")
            if token:
                self.token = token
        except Exception as exc:  # noqa: BLE001
            logger.warning("LinkedIn token refresh failed: %s", exc)

    def discover_companies(self, keywords: list[str]) -> list[CompanyCandidate]:
        # LinkedIn discovery APIs are permission-gated. This method attempts the endpoint
        # and gracefully returns no candidates on unsupported accounts.
        candidates: list[CompanyCandidate] = []
        for keyword in keywords:
            url = f"{self.base_url}/organizationAcls"
            params = {
                "q": "roleAssignee",
                "projection": "(elements*(organization~(id,localizedName,vanityName,websiteUrl)))",
            }
            try:
                payload = self._get(url, params=params)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LinkedIn discovery not available for token; falling back to curated list. keyword=%s error=%s",
                    keyword,
                    exc,
                )
                continue
            for item in payload.get("elements", []):
                org = item.get("organization~") or {}
                name = org.get("localizedName")
                if not name:
                    continue
                if keyword.lower() not in name.lower():
                    continue
                vanity = org.get("vanityName")
                profile_url = f"https://www.linkedin.com/company/{vanity}/" if vanity else ""
                candidates.append(
                    CompanyCandidate(
                        platform="linkedin",
                        name=name,
                        profile_url=profile_url,
                        platform_company_id=str(org.get("id")) if org.get("id") else None,
                        confidence=0.7,
                        source_keyword=keyword,
                        metadata={"website_url": org.get("websiteUrl")},
                    )
                )
        return candidates

    def fetch_posts(
        self, company: CompanyRef, since: datetime, until: datetime
    ) -> list[RawPost]:
        if not company.platform_company_id:
            logger.warning("Skipping LinkedIn company with missing platform_company_id: %s", company.name)
            return []

        author = f"List(urn:li:organization:{company.platform_company_id})"
        url = f"{self.base_url}/ugcPosts"
        params = {
            "q": "authors",
            "authors": author,
            "count": 100,
            "sortBy": "LAST_MODIFIED",
        }
        try:
            payload = self._get(url, params=params)
        except Exception as exc:  # noqa: BLE001
            logger.error("LinkedIn fetch failed for %s: %s", company.name, exc)
            return []

        results: list[RawPost] = []
        for item in payload.get("elements", []):
            created_ts = (
                item.get("created", {})
                .get("time")
            )
            if created_ts is None:
                continue
            published_at = datetime.fromtimestamp(created_ts / 1000, tz=timezone.utc)
            if published_at < since or published_at > until:
                continue

            text = (
                item.get("specificContent", {})
                .get("com.linkedin.ugc.ShareContent", {})
                .get("shareCommentary", {})
                .get("text", "")
            )
            media = (
                item.get("specificContent", {})
                .get("com.linkedin.ugc.ShareContent", {})
                .get("media", [])
            )
            media_type = self._infer_media_type(media)
            social = item.get("socialDetail", {})
            metrics = {
                "likes": social.get("totalSocialActivityCounts", {}).get("numLikes"),
                "comments": social.get("totalSocialActivityCounts", {}).get("numComments"),
                "shares": social.get("totalSocialActivityCounts", {}).get("numShares"),
                "views": None,
            }
            results.append(
                RawPost(
                    post_id=item.get("id", ""),
                    text=text,
                    published_at=published_at,
                    media_type=media_type,
                    metrics=metrics,
                    metadata=item,
                )
            )
        return results

    def normalize(self, raw: RawPost, company: CompanyRef) -> NormalizedPost:
        text = raw.text or ""
        return NormalizedPost(
            platform="linkedin",
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
    def _infer_media_type(media: list[dict[str, Any]]) -> str:
        if not media:
            return "text"
        kinds = set()
        for item in media:
            status = item.get("status", "").lower()
            if "video" in status:
                kinds.add("video")
            elif "image" in status:
                kinds.add("image")
            elif "document" in status:
                kinds.add("document")
            else:
                kinds.add("unknown")
        if len(kinds) == 1:
            return kinds.pop()
        return "mixed"
