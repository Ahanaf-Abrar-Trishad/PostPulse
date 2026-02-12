from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import sessionmaker

from app.analyzer.service import AnalyzerService
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import PlatformLimiter
from app.db.repository import Repository
from app.db.session import session_scope
from app.generator.service import ContentGeneratorService
from app.scrapers.facebook import FacebookCollector
from app.scrapers.fallback_playwright import PlaywrightFallbackCollector
from app.scrapers.linkedin import LinkedInCollector

logger = get_logger(__name__)


class Orchestrator:
    def __init__(self, settings: Settings, session_factory: sessionmaker) -> None:
        self.settings = settings
        self.session_factory = session_factory

        self.linkedin_collector = LinkedInCollector(
            settings=settings,
            limiter=PlatformLimiter(settings.config.rate_limit.linkedin),
        )
        self.facebook_collector = FacebookCollector(
            settings=settings,
            limiter=PlatformLimiter(settings.config.rate_limit.facebook),
        )
        self.fallback_collector = PlaywrightFallbackCollector(
            settings=settings,
            limiter=PlatformLimiter(settings.config.rate_limit.fallback),
        )
        self.analyzer = AnalyzerService()
        self.generator = ContentGeneratorService(settings=settings)

    def bootstrap_companies(self) -> int:
        configured = [company.model_dump() for company in self.settings.config.companies]
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            count = repo.sync_companies_from_config(configured)
        logger.info("Company bootstrap complete. count=%s", count)
        return count

    def discover_candidates(self, keywords_override: list[str] | None = None) -> dict[str, Any]:
        keywords = keywords_override or self.settings.config.discovery.keywords
        if not keywords:
            logger.warning("No discovery keywords configured; skipping discovery")
            return {
                "inserted": 0,
                "platforms": [],
                "candidates_promoted": 0,
                "ignored_due_to_monitor_limit": 0,
            }

        inserted = 0
        candidates_promoted = 0
        ignored_due_to_monitor_limit = 0
        platforms_used: list[str] = []
        max_monitored = self.settings.config.discovery.max_monitored_companies
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            active_company_count = repo.count_active_companies()
            for collector in [self.linkedin_collector, self.facebook_collector]:
                try:
                    collector.authenticate()
                    candidates = collector.discover_companies(keywords)
                    platforms_used.append(collector.platform)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Discovery skipped for platform=%s error=%s", collector.platform, exc)
                    continue
                for candidate in candidates:
                    repo.upsert_company_candidate(candidate)
                    inserted += 1
                    if active_company_count >= max_monitored:
                        ignored_due_to_monitor_limit += 1
        payload = {
            "inserted": inserted,
            "platforms": platforms_used,
            "keywords": keywords,
            "candidates_promoted": candidates_promoted,
            "ignored_due_to_monitor_limit": ignored_due_to_monitor_limit,
        }
        self._notify("discover.completed", payload)
        return payload

    def scrape_posts(
        self,
        platform: str = "all",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        until = until or datetime.now(timezone.utc)
        failures = 0
        processed = 0
        fallback_used = 0
        skipped_missing_platform_id = 0
        fallback_skipped_no_date = 0
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            run = repo.create_scrape_run(job_type="scrape", platform=platform)
            run_id = run.id

            target_platforms = self._resolve_platforms(platform)
            refs = repo.get_active_company_refs(platforms=target_platforms)

            for company in refs:
                collector = self._collector_for(company.platform)
                if collector is None:
                    failures += 1
                    continue
                if not company.platform_company_id:
                    skipped_missing_platform_id += 1
                    logger.warning(
                        "Skipping company due to missing platform ID. company=%s platform=%s",
                        company.name,
                        company.platform,
                    )
                    continue
                try:
                    collector.authenticate()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Collector auth failed platform=%s error=%s", company.platform, exc)
                    failures += 1
                    continue
                company_since = since or self._compute_default_since(repo, company.id, company.platform)
                try:
                    raw_posts = collector.fetch_posts(company, company_since, until)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Primary fetch failed company=%s platform=%s error=%s", company.name, company.platform, exc)
                    raw_posts = []
                    failures += 1

                if not raw_posts and self.settings.config.scrape.include_playwright_fallback:
                    fallback = self.fallback_collector.fetch_posts(company, company_since, until)
                    fallback_skipped_no_date += self.fallback_collector.last_skipped_no_date
                    if fallback:
                        fallback_used += 1
                        raw_posts = fallback
                        normalized = [self.fallback_collector.normalize(item, company) for item in raw_posts]
                    else:
                        normalized = []
                else:
                    normalized = [collector.normalize(item, company) for item in raw_posts]

                newest: datetime | None = None
                for raw_item, norm_item in zip(raw_posts, normalized):
                    repo.upsert_post(norm_item, raw_payload=raw_item.metadata)
                    processed += 1
                    if newest is None or norm_item.published_at > newest:
                        newest = norm_item.published_at
                repo.update_watermark(company.id, company.platform, newest)

            status = "success"
            has_issues = failures > 0 or skipped_missing_platform_id > 0
            if has_issues and processed > 0:
                status = "partial_success"
            elif has_issues and processed == 0:
                status = "failed"
            details = {
                "companies_processed": len(refs),
                "posts_processed": processed,
                "failures": failures,
                "fallback_used": fallback_used,
                "skipped_missing_platform_id": skipped_missing_platform_id,
                "fallback_skipped_no_date": fallback_skipped_no_date,
            }
            repo.finish_scrape_run(
                run_id=run_id,
                status=status,
                processed_count=processed,
                error_message=None if status != "failed" else "No posts processed",
                details=details,
            )
        payload = {
            "status": status,
            "posts_processed": processed,
            "failures": failures,
            "fallback_used": fallback_used,
            "skipped_missing_platform_id": skipped_missing_platform_id,
            "fallback_skipped_no_date": fallback_skipped_no_date,
        }
        self._notify("scrape.completed", payload)
        return payload

    def list_candidates(self, platform: str = "all", active_only: bool = False) -> dict[str, Any]:
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            candidates = repo.list_candidates(platform=platform, active_only=active_only)
        return {
            "count": len(candidates),
            "items": [
                {
                    "id": str(item.id),
                    "platform": item.platform,
                    "name": item.name,
                    "profile_url": item.profile_url,
                    "platform_company_id": item.platform_company_id,
                    "confidence": item.confidence,
                    "source_keyword": item.source_keyword,
                    "active": item.active,
                }
                for item in candidates
            ],
        }

    def activate_candidate(self, candidate_id: UUID) -> dict[str, Any]:
        max_monitored = self.settings.config.discovery.max_monitored_companies
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            candidate = repo.get_candidate(candidate_id)
            if candidate is None:
                raise ValueError(f"Candidate not found: {candidate_id}")
            if candidate.active:
                return {
                    "status": "already_active",
                    "candidate_id": str(candidate_id),
                    "ignored_due_to_monitor_limit": 0,
                }
            active_count = repo.count_active_companies()
            if active_count >= max_monitored:
                return {
                    "status": "ignored",
                    "candidate_id": str(candidate_id),
                    "ignored_due_to_monitor_limit": 1,
                }
            repo.activate_candidate(candidate_id)
        return {
            "status": "activated",
            "candidate_id": str(candidate_id),
            "ignored_due_to_monitor_limit": 0,
        }

    def promote_candidate(self, candidate_id: UUID) -> dict[str, Any]:
        max_monitored = self.settings.config.discovery.max_monitored_companies
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            candidate = repo.get_candidate(candidate_id)
            if candidate is None:
                raise ValueError(f"Candidate not found: {candidate_id}")
            active_count = repo.count_active_companies()
            if active_count >= max_monitored:
                return {
                    "status": "ignored",
                    "candidate_id": str(candidate_id),
                    "ignored_due_to_monitor_limit": 1,
                    "candidates_promoted": 0,
                }
            company_id = repo.promote_candidate_to_company(candidate_id)
        return {
            "status": "promoted",
            "candidate_id": str(candidate_id),
            "company_id": str(company_id),
            "ignored_due_to_monitor_limit": 0,
            "candidates_promoted": 1,
        }

    def analyze(self, window_days: int | None = None) -> dict[str, Any]:
        window_days = window_days or self.settings.config.scrape.backfill_days
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            run = repo.create_analysis_run(window_days=window_days)
            try:
                posts = repo.get_posts_for_analysis(window_days=window_days)
                result = self.analyzer.analyze_posts(posts, window_days=window_days)
                for insight_type, payload in result.insights:
                    repo.add_analysis_insight(run.id, insight_type, payload)
                repo.finish_analysis_run(
                    run_id=run.id,
                    status="success",
                    summary_markdown=result.summary_markdown,
                    summary_json=result.summary_json,
                )
                output = {
                    "analysis_run_id": str(run.id),
                    "posts_analyzed": len(posts),
                    "status": "success",
                }
            except Exception as exc:  # noqa: BLE001
                repo.finish_analysis_run(
                    run_id=run.id,
                    status="failed",
                    summary_markdown="",
                    summary_json={},
                    error_message=str(exc),
                )
                output = {"analysis_run_id": str(run.id), "status": "failed", "error": str(exc)}
        self._notify("analyze.completed", output)
        return output

    def generate_content(self, count: int | None = None, platforms: list[str] | None = None) -> dict[str, Any]:
        count = count or self.settings.config.generation.default_count
        platforms = platforms or ["linkedin", "facebook"]
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            latest = repo.get_latest_completed_analysis()
            if latest is None:
                raise RuntimeError("No completed analysis run found. Run analyze first.")
            source_texts = repo.list_recent_source_texts(limit=1500)
            insights = latest.summary_json
            generated = self.generator.generate_posts(
                insights=insights,
                source_texts=source_texts,
                count=count,
                platforms=platforms,
                language=self.settings.config.generation.default_language,
            )
            for item in generated:
                repo.save_generated_post(
                    analysis_run_id=latest.id,
                    platform=item.platform,
                    content=item.content,
                    hashtags=item.hashtags,
                    cta=item.cta,
                    prompt_hash=item.prompt_hash,
                    model_name=item.model_name,
                    similarity_score=item.similarity_score,
                    validation_flags=item.validation_flags,
                )
        payload = {"count": len(generated), "platforms": platforms}
        self._notify("generate.completed", payload)
        return payload

    def export_data(self, format_name: str, out_dir: str | None = None) -> dict[str, Any]:
        out_path = Path(out_dir or self.settings.config.export.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            posts_df = repo.posts_to_dataframe(window_days=self.settings.config.scrape.backfill_days)
            generated_df = repo.generated_posts_to_dataframe()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        paths: list[str] = []
        if format_name == "csv":
            posts_file = out_path / f"posts_{timestamp}.csv"
            generated_file = out_path / f"generated_{timestamp}.csv"
            posts_df.to_csv(posts_file, index=False)
            generated_df.to_csv(generated_file, index=False)
            paths.extend([str(posts_file), str(generated_file)])
        elif format_name == "json":
            posts_file = out_path / f"posts_{timestamp}.json"
            generated_file = out_path / f"generated_{timestamp}.json"
            posts_file.write_text(posts_df.to_json(orient="records", indent=2), encoding="utf-8")
            generated_file.write_text(generated_df.to_json(orient="records", indent=2), encoding="utf-8")
            paths.extend([str(posts_file), str(generated_file)])
        elif format_name == "xlsx":
            book_file = out_path / f"socialintel_{timestamp}.xlsx"
            with pd.ExcelWriter(book_file, engine="openpyxl") as writer:  # type: ignore[name-defined]
                posts_df.to_excel(writer, sheet_name="posts", index=False)
                generated_df.to_excel(writer, sheet_name="generated", index=False)
            paths.append(str(book_file))
        else:
            raise ValueError(f"Unsupported export format: {format_name}")
        payload = {"format": format_name, "files": paths}
        self._notify("export.completed", payload)
        return payload

    def run_daily(self) -> dict[str, Any]:
        discover = self.discover_candidates()
        scrape = self.scrape_posts(platform="all")
        analyze = self.analyze(window_days=self.settings.config.scrape.backfill_days)
        generate = self.generate_content(
            count=self.settings.config.generation.default_count,
            platforms=["linkedin", "facebook"],
        )
        return {
            "discover": discover,
            "scrape": scrape,
            "analyze": analyze,
            "generate": generate,
        }

    def _compute_default_since(self, repo: Repository, company_id: UUID, platform: str) -> datetime:
        watermark = repo.get_watermark(company_id=company_id, platform=platform)
        if watermark:
            return watermark - timedelta(hours=self.settings.config.scrape.lookback_hours_on_incremental)
        return datetime.now(timezone.utc) - timedelta(days=self.settings.config.scrape.backfill_days)

    def _collector_for(self, platform: str):
        if platform == "linkedin":
            return self.linkedin_collector
        if platform == "facebook":
            return self.facebook_collector
        return None

    @staticmethod
    def _resolve_platforms(platform: str) -> list[str]:
        if platform == "all":
            return ["linkedin", "facebook"]
        return [platform]

    def _notify(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.settings.config.notifications.webhook_enabled:
            return
        webhook_url = self.settings.secrets.webhook_url
        if not webhook_url:
            return
        body = {"event": event_type, "payload": payload, "sent_at": datetime.now(timezone.utc).isoformat()}
        try:
            response = httpx.post(
                webhook_url,
                json=body,
                timeout=self.settings.config.notifications.webhook_timeout_seconds,
            )
            success = response.status_code < 300
            status_code = response.status_code
            response_body = response.text[:2000]
        except Exception as exc:  # noqa: BLE001
            success = False
            status_code = None
            response_body = str(exc)

        with session_scope(self.session_factory) as session:
            repo = Repository(session)
            repo.record_webhook_delivery(
                event_type=event_type,
                payload=body,
                target_url=webhook_url,
                status_code=status_code,
                success=success,
                response_body=response_body,
            )
        if not success:
            logger.warning("Webhook delivery failed event=%s detail=%s", event_type, response_body)


# Imported late because pandas is used only for exporting and avoids import cost during bootstrap.
import pandas as pd  # noqa: E402  pylint: disable=wrong-import-position
