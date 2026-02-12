from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.config import AppConfig, Settings, write_config
from app.core.logging import get_logger
from app.db.repository import Repository
from app.db.session import session_scope
from app.orchestrator import Orchestrator

logger = get_logger(__name__)


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


def create_app(settings: Settings, orchestrator: Orchestrator) -> FastAPI:
    app = FastAPI(title="SocialIntel Local UI", version="0.1.0")

    @app.get("/")
    def dashboard() -> dict[str, Any]:
        with session_scope(orchestrator.session_factory) as session:
            repo = Repository(session)
            runs = repo.list_recent_runs(limit=10)
        return {
            "service": "socialintel",
            "status": "ok",
            "recent_runs": [
                {
                    "id": str(run.id),
                    "job_type": run.job_type,
                    "platform": run.platform,
                    "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "processed_count": run.processed_count,
                }
                for run in runs
            ],
        }

    @app.get("/runs")
    def list_runs(limit: int = 50) -> dict[str, Any]:
        with session_scope(orchestrator.session_factory) as session:
            repo = Repository(session)
            runs = repo.list_recent_runs(limit=min(limit, 200))
        return {
            "runs": [
                {
                    "id": str(run.id),
                    "job_type": run.job_type,
                    "platform": run.platform,
                    "status": run.status,
                    "processed_count": run.processed_count,
                    "error_message": run.error_message,
                    "details": run.details,
                }
                for run in runs
            ]
        }

    @app.get("/logs")
    def logs(page: int = 1, page_size: int = 100) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(500, page_size))
        log_path = Path("logs/socialintel.log")
        if not log_path.exists():
            return {"items": [], "page": page, "page_size": page_size, "total": 0}
        lines = log_path.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        start = (page - 1) * page_size
        end = start + page_size
        selected = lines[start:end]
        items: list[dict[str, Any]] = []
        for line in selected:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                items.append({"raw": line})
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    @app.get("/config")
    def get_config() -> dict[str, Any]:
        return settings.config.to_editable_dict()

    @app.post("/config")
    def update_config(payload: ConfigUpdateRequest) -> dict[str, Any]:
        try:
            parsed = AppConfig.model_validate(payload.config)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        write_config(settings.config.web_ui.editable_config_path, parsed)
        settings.config = parsed
        return {"status": "updated"}

    @app.post("/trigger/{job}")
    def trigger_job(job: str) -> dict[str, Any]:
        if job == "discover":
            return orchestrator.discover_candidates()
        if job == "scrape":
            return orchestrator.scrape_posts(platform="all")
        if job == "analyze":
            return orchestrator.analyze()
        if job == "generate":
            return orchestrator.generate_content()
        raise HTTPException(status_code=404, detail=f"Unknown job: {job}")

    return app
