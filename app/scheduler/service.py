from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Settings
from app.core.logging import get_logger
from app.orchestrator import Orchestrator

logger = get_logger(__name__)


class SchedulerService:
    def __init__(self, settings: Settings, orchestrator: Orchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.scheduler = BlockingScheduler(timezone=settings.config.scheduler.timezone)

    def register_jobs(self) -> None:
        sched = self.settings.config.scheduler
        self.scheduler.add_job(
            self.orchestrator.discover_candidates,
            trigger=CronTrigger.from_crontab(sched.discover_cron, timezone=sched.timezone),
            id="discover",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.orchestrator.scrape_posts,
            trigger=CronTrigger.from_crontab(sched.scrape_cron, timezone=sched.timezone),
            id="scrape",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.orchestrator.analyze,
            trigger=CronTrigger.from_crontab(sched.analyze_cron, timezone=sched.timezone),
            id="analyze",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.orchestrator.generate_content,
            trigger=CronTrigger.from_crontab(sched.generate_cron, timezone=sched.timezone),
            id="generate",
            replace_existing=True,
        )

    def run(self) -> None:
        self.register_jobs()
        logger.info("Scheduler started with jobs=%s", [job.id for job in self.scheduler.get_jobs()])
        self.scheduler.start()
