from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import (
    AnalysisInsight,
    AnalysisRun,
    Company,
    CompanyCandidate,
    CompanyPlatformAccount,
    GeneratedPost,
    Post,
    PostMetricSnapshot,
    ScrapeRun,
    WebhookDelivery,
)
from app.scrapers.base import CompanyCandidate as CandidateDTO
from app.scrapers.base import CompanyRef, NormalizedPost

logger = get_logger(__name__)


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def sync_companies_from_config(self, configured_companies: list[dict[str, Any]]) -> int:
        created_or_updated = 0
        for item in configured_companies:
            company = self.session.scalar(select(Company).where(Company.name == item["name"]))
            if company is None:
                company = Company(
                    name=item["name"],
                    website=item.get("website"),
                    active=item.get("active", True),
                )
                self.session.add(company)
                self.session.flush()
            else:
                company.website = item.get("website") or company.website
                company.active = item.get("active", company.active)
            created_or_updated += 1
            self._ensure_platform_account(
                company=company,
                platform="linkedin",
                profile_url=item.get("linkedin_url"),
                platform_company_id=item.get("linkedin_company_id"),
            )
            self._ensure_platform_account(
                company=company,
                platform="facebook",
                profile_url=item.get("facebook_url"),
                platform_company_id=item.get("facebook_page_id"),
            )
        # Keep config-sync behavior deterministic for callers that read immediately after sync
        # while using sessions with autoflush disabled.
        self.session.flush()
        return created_or_updated

    def _ensure_platform_account(
        self,
        company: Company,
        platform: str,
        profile_url: str | None,
        platform_company_id: str | None = None,
    ) -> None:
        effective_profile_url = (
            (profile_url or "").strip()
            or self._default_profile_url(platform, platform_company_id)
        )
        if not effective_profile_url and not platform_company_id:
            return
        account = self.session.scalar(
            select(CompanyPlatformAccount).where(
                CompanyPlatformAccount.company_id == company.id,
                CompanyPlatformAccount.platform == platform,
            )
        )
        if account is None:
            account = CompanyPlatformAccount(
                company_id=company.id,
                platform=platform,
                profile_url=effective_profile_url,
                platform_company_id=platform_company_id,
            )
            self.session.add(account)
        else:
            if effective_profile_url:
                account.profile_url = effective_profile_url
            if platform_company_id:
                account.platform_company_id = platform_company_id

    def upsert_company_candidate(self, candidate: CandidateDTO) -> tuple[UUID, bool]:
        existing = self.session.scalar(
            select(CompanyCandidate).where(
                CompanyCandidate.platform == candidate.platform,
                CompanyCandidate.profile_url == candidate.profile_url,
            )
        )
        if existing:
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.source_keyword = candidate.source_keyword
            existing.metadata_json = candidate.metadata
            if candidate.platform_company_id and not existing.platform_company_id:
                existing.platform_company_id = candidate.platform_company_id
            if candidate.name:
                existing.name = candidate.name
            return existing.id, False
        record = CompanyCandidate(
            platform=candidate.platform,
            name=candidate.name,
            profile_url=candidate.profile_url,
            platform_company_id=candidate.platform_company_id,
            confidence=candidate.confidence,
            source_keyword=candidate.source_keyword,
            metadata_json=candidate.metadata,
            active=False,
        )
        self.session.add(record)
        self.session.flush()
        return record.id, True

    def get_candidate(self, candidate_id: UUID) -> CompanyCandidate | None:
        return self.session.get(CompanyCandidate, candidate_id)

    def list_candidates(
        self,
        platform: str | None = None,
        active_only: bool = False,
        limit: int = 500,
    ) -> list[CompanyCandidate]:
        stmt = select(CompanyCandidate).order_by(
            CompanyCandidate.active.desc(),
            CompanyCandidate.confidence.desc(),
            CompanyCandidate.created_at.desc(),
        )
        if platform and platform != "all":
            stmt = stmt.where(CompanyCandidate.platform == platform)
        if active_only:
            stmt = stmt.where(CompanyCandidate.active.is_(True))
        stmt = stmt.limit(max(1, min(limit, 2000)))
        return list(self.session.scalars(stmt).all())

    def activate_candidate(self, candidate_id: UUID) -> None:
        candidate = self.session.get(CompanyCandidate, candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")
        candidate.active = True

    @staticmethod
    def is_candidate_auto_promotable(
        candidate: CompanyCandidate,
        min_confidence: float,
    ) -> bool:
        return bool(
            candidate.platform_company_id
            and (candidate.profile_url or "").strip()
            and candidate.confidence >= min_confidence
        )

    def promote_candidate_to_company(self, candidate_id: UUID) -> UUID:
        candidate = self.session.get(CompanyCandidate, candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")
        company = self._find_company_by_normalized_name(candidate.name)
        if company is None:
            company = Company(name=candidate.name, active=True)
            self.session.add(company)
            self.session.flush()
        else:
            company.active = True

        self._ensure_platform_account(
            company=company,
            platform=candidate.platform,
            profile_url=candidate.profile_url,
            platform_company_id=candidate.platform_company_id,
        )
        candidate.active = True
        self.session.flush()
        return company.id

    def get_active_company_refs(self, platforms: list[str] | None = None) -> list[CompanyRef]:
        stmt = (
            select(CompanyPlatformAccount, Company)
            .join(Company, Company.id == CompanyPlatformAccount.company_id)
            .where(Company.active.is_(True))
        )
        if platforms:
            stmt = stmt.where(CompanyPlatformAccount.platform.in_(platforms))
        rows = self.session.execute(stmt).all()
        refs: list[CompanyRef] = []
        for account, company in rows:
            refs.append(
                CompanyRef(
                    id=company.id,
                    name=company.name,
                    profile_url=account.profile_url,
                    platform=account.platform,  # type: ignore[arg-type]
                    platform_company_id=account.platform_company_id,
                )
            )
        return refs

    def count_active_companies(self) -> int:
        stmt = select(func.count(Company.id)).where(Company.active.is_(True))
        value = self.session.scalar(stmt)
        return int(value or 0)

    def create_scrape_run(self, job_type: str, platform: str = "all") -> ScrapeRun:
        run = ScrapeRun(job_type=job_type, platform=platform, status="running")
        self.session.add(run)
        self.session.flush()
        return run

    def finish_scrape_run(
        self,
        run_id: UUID,
        status: str,
        processed_count: int,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        run = self.session.get(ScrapeRun, run_id)
        if not run:
            return
        run.status = status
        run.processed_count = processed_count
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        if details:
            run.details = details

    def upsert_post(self, post: NormalizedPost, raw_payload: dict[str, Any] | None = None) -> UUID:
        existing = self.session.scalar(
            select(Post).where(
                Post.platform == post.platform,
                Post.platform_post_id == post.platform_post_id,
            )
        )
        if existing is None:
            existing = Post(
                company_id=post.company_id,
                platform=post.platform,
                platform_post_id=post.platform_post_id,
                company_name=post.company_name,
                company_profile_url=post.company_profile_url,
                post_text=post.post_text,
                published_at=post.published_at,
                media_type=post.media_type,
                hashtags=post.hashtags,
                links=post.links,
                cta_text=post.cta_text,
                post_structure=post.post_structure,
                metrics=post.metrics,
                metrics_provenance=post.metrics_provenance,
                raw_payload=raw_payload or {},
            )
            self.session.add(existing)
            self.session.flush()
        else:
            existing.post_text = post.post_text
            existing.published_at = post.published_at
            existing.media_type = post.media_type
            existing.hashtags = post.hashtags
            existing.links = post.links
            existing.cta_text = post.cta_text
            existing.post_structure = post.post_structure
            existing.metrics = post.metrics
            existing.metrics_provenance = post.metrics_provenance
            if raw_payload:
                existing.raw_payload = raw_payload

        snapshot = PostMetricSnapshot(
            post_id=existing.id,
            likes=post.metrics.get("likes"),
            comments=post.metrics.get("comments"),
            shares=post.metrics.get("shares"),
            views=post.metrics.get("views"),
            provenance=post.metrics_provenance,
        )
        self.session.add(snapshot)
        return existing.id

    def update_watermark(
        self, company_id: UUID, platform: str, published_at: datetime | None
    ) -> None:
        if published_at is None:
            return
        account = self.session.scalar(
            select(CompanyPlatformAccount).where(
                CompanyPlatformAccount.company_id == company_id,
                CompanyPlatformAccount.platform == platform,
            )
        )
        if account is None:
            return
        if account.last_successful_published_at is None or published_at > account.last_successful_published_at:
            account.last_successful_published_at = published_at

    def get_watermark(self, company_id: UUID, platform: str) -> datetime | None:
        account = self.session.scalar(
            select(CompanyPlatformAccount).where(
                CompanyPlatformAccount.company_id == company_id,
                CompanyPlatformAccount.platform == platform,
            )
        )
        return account.last_successful_published_at if account else None

    def get_posts_for_analysis(self, window_days: int) -> list[Post]:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        stmt = select(Post).where(Post.published_at >= since).order_by(Post.published_at.desc())
        return list(self.session.scalars(stmt).all())

    def create_analysis_run(self, window_days: int) -> AnalysisRun:
        run = AnalysisRun(window_days=window_days, status="running")
        self.session.add(run)
        self.session.flush()
        return run

    def finish_analysis_run(
        self,
        run_id: UUID,
        status: str,
        summary_markdown: str,
        summary_json: dict[str, Any],
        error_message: str | None = None,
    ) -> None:
        run = self.session.get(AnalysisRun, run_id)
        if not run:
            return
        run.status = status
        run.summary_markdown = summary_markdown
        run.summary_json = summary_json
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = error_message

    def add_analysis_insight(self, run_id: UUID, insight_type: str, payload: dict[str, Any]) -> UUID:
        insight = AnalysisInsight(analysis_run_id=run_id, insight_type=insight_type, payload=payload)
        self.session.add(insight)
        self.session.flush()
        return insight.id

    def get_latest_completed_analysis(self) -> AnalysisRun | None:
        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.status == "success")
            .order_by(AnalysisRun.finished_at.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def list_insights_for_run(self, run_id: UUID) -> list[AnalysisInsight]:
        stmt = select(AnalysisInsight).where(AnalysisInsight.analysis_run_id == run_id)
        return list(self.session.scalars(stmt).all())

    def save_generated_post(
        self,
        analysis_run_id: UUID | None,
        platform: str,
        content: str,
        hashtags: list[str],
        cta: str | None,
        prompt_hash: str,
        model_name: str,
        similarity_score: float,
        validation_flags: list[str],
    ) -> UUID:
        record = GeneratedPost(
            analysis_run_id=analysis_run_id,
            platform=platform,
            content=content,
            hashtags=hashtags,
            cta=cta,
            prompt_hash=prompt_hash,
            model_name=model_name,
            similarity_score=similarity_score,
            validation_flags=validation_flags,
        )
        self.session.add(record)
        self.session.flush()
        return record.id

    def list_recent_source_texts(self, limit: int = 1000) -> list[str]:
        stmt = select(Post.post_text).order_by(Post.published_at.desc()).limit(limit)
        return [text for text in self.session.scalars(stmt).all() if text]

    def list_generated_posts(self, limit: int = 200) -> list[GeneratedPost]:
        stmt = select(GeneratedPost).order_by(GeneratedPost.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def list_recent_runs(self, limit: int = 50) -> list[ScrapeRun]:
        stmt = select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def record_webhook_delivery(
        self,
        event_type: str,
        payload: dict[str, Any],
        target_url: str,
        status_code: int | None,
        success: bool,
        response_body: str | None = None,
    ) -> UUID:
        delivery = WebhookDelivery(
            event_type=event_type,
            payload=payload,
            target_url=target_url,
            status_code=status_code,
            success=success,
            response_body=response_body,
        )
        self.session.add(delivery)
        self.session.flush()
        return delivery.id

    def posts_to_dataframe(self, window_days: int = 90) -> pd.DataFrame:
        posts = self.get_posts_for_analysis(window_days=window_days)
        rows = [
            {
                "id": str(post.id),
                "platform": post.platform,
                "company_name": post.company_name,
                "published_at": post.published_at.isoformat(),
                "media_type": post.media_type,
                "post_text": post.post_text,
                "hashtags": ",".join(post.hashtags or []),
                "links": ",".join(post.links or []),
                "cta_text": post.cta_text,
                "likes": (post.metrics or {}).get("likes"),
                "comments": (post.metrics or {}).get("comments"),
                "shares": (post.metrics or {}).get("shares"),
                "views": (post.metrics or {}).get("views"),
            }
            for post in posts
        ]
        return pd.DataFrame(rows)

    def generated_posts_to_dataframe(self, limit: int = 500) -> pd.DataFrame:
        posts = self.list_generated_posts(limit=limit)
        rows = [
            {
                "id": str(post.id),
                "platform": post.platform,
                "content": post.content,
                "hashtags": ",".join(post.hashtags or []),
                "cta": post.cta,
                "model_name": post.model_name,
                "similarity_score": post.similarity_score,
                "flags": ",".join(post.validation_flags or []),
                "created_at": post.created_at.isoformat() if post.created_at else "",
            }
            for post in posts
        ]
        return pd.DataFrame(rows)

    @staticmethod
    def _normalize_company_name(name: str) -> str:
        return re.sub(r"\s+", " ", (name or "").strip().lower())

    def _find_company_by_normalized_name(self, name: str) -> Company | None:
        normalized_target = self._normalize_company_name(name)
        if not normalized_target:
            return None
        exact = self.session.scalar(select(Company).where(Company.name == name))
        if exact is not None:
            return exact
        companies = self.session.scalars(select(Company)).all()
        for company in companies:
            if self._normalize_company_name(company.name) == normalized_target:
                return company
        return None

    @staticmethod
    def _default_profile_url(platform: str, platform_company_id: str | None) -> str:
        if not platform_company_id:
            return ""
        if platform == "linkedin":
            return f"https://www.linkedin.com/company/{platform_company_id}/"
        if platform == "facebook":
            return f"https://www.facebook.com/{platform_company_id}"
        return ""
