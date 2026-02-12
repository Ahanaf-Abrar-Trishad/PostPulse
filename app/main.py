from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
import uvicorn

from app.core.config import load_settings, reset_settings_cache
from app.core.logging import setup_logging
from app.db.session import get_session_factory, init_db
from app.orchestrator import Orchestrator
from app.scheduler.service import SchedulerService
from app.ui.server import create_app

cli = typer.Typer(help="Social Intelligence pipeline CLI")


def _bootstrap(config_path: str) -> tuple:
    reset_settings_cache()
    settings = load_settings(config_path)
    setup_logging()
    session_factory = get_session_factory(settings)
    orchestrator = Orchestrator(settings=settings, session_factory=session_factory)
    return settings, session_factory, orchestrator


@cli.command("init-db")
def init_db_command(
    config_path: Annotated[str, typer.Option("--config", help="Path to config YAML")] = "config/config.yaml",
) -> None:
    settings, _, orchestrator = _bootstrap(config_path)
    init_db(settings)
    orchestrator.bootstrap_companies()
    typer.echo("Database initialized and config companies synced.")


@cli.command("discover")
def discover_command(
    keywords_file: Annotated[
        str,
        typer.Option("--keywords-file", help="Text file containing one keyword per line"),
    ] = "config/keywords.txt",
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    keywords_override: list[str] | None = None
    path = Path(keywords_file)
    if path.exists():
        keywords_override = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = orchestrator.discover_candidates(keywords_override=keywords_override)
    typer.echo(json.dumps(result, indent=2))


@cli.command("scrape")
def scrape_command(
    platform: Annotated[str, typer.Option("--platform")] = "all",
    since: Annotated[str | None, typer.Option("--since", help="ISO date e.g. 2025-11-14")] = None,
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    since_dt: datetime | None = None
    if since:
        parsed = datetime.fromisoformat(since)
        since_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    result = orchestrator.scrape_posts(platform=platform, since=since_dt)
    typer.echo(json.dumps(result, indent=2))


@cli.command("analyze")
def analyze_command(
    window_days: Annotated[int, typer.Option("--window-days")] = 90,
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    result = orchestrator.analyze(window_days=window_days)
    typer.echo(json.dumps(result, indent=2))


@cli.command("generate")
def generate_command(
    count: Annotated[int, typer.Option("--count")] = 12,
    platform: Annotated[str, typer.Option("--platform", help="linkedin|facebook|all")] = "all",
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    platforms = ["linkedin", "facebook"] if platform == "all" else [platform]
    result = orchestrator.generate_content(count=count, platforms=platforms)
    typer.echo(json.dumps(result, indent=2))


@cli.command("export")
def export_command(
    format_name: Annotated[str, typer.Option("--format")] = "csv",
    out: Annotated[str, typer.Option("--out")] = "exports",
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    result = orchestrator.export_data(format_name=format_name, out_dir=out)
    typer.echo(json.dumps(result, indent=2))


@cli.command("run-daily")
def run_daily_command(
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    result = orchestrator.run_daily()
    typer.echo(json.dumps(result, indent=2))


@cli.command("ui")
def ui_command(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8080,
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    settings, _, orchestrator = _bootstrap(config_path)
    app = create_app(settings=settings, orchestrator=orchestrator)
    uvicorn.run(app, host=host, port=port)


@cli.command("schedule")
def schedule_command(
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    scheduler = SchedulerService(settings=orchestrator.settings, orchestrator=orchestrator)
    scheduler.run()


@cli.command("seed-companies")
def seed_companies(
    file: Annotated[str, typer.Option("--file", help="JSON file with company configs")] = "",
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    settings, _, orchestrator = _bootstrap(config_path)
    path = Path(file)
    if file and path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        settings.config.companies = payload.get("companies", settings.config.companies)
    count = orchestrator.bootstrap_companies()
    typer.echo(json.dumps({"seeded": count}, indent=2))


@cli.command("candidates-list")
def candidates_list_command(
    platform: Annotated[str, typer.Option("--platform", help="linkedin|facebook|all")] = "all",
    active_only: Annotated[bool, typer.Option("--active-only")] = False,
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    result = orchestrator.list_candidates(platform=platform, active_only=active_only)
    typer.echo(json.dumps(result, indent=2))


@cli.command("candidates-activate")
def candidates_activate_command(
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    result = orchestrator.activate_candidate(UUID(candidate_id))
    typer.echo(json.dumps(result, indent=2))


@cli.command("candidates-promote")
def candidates_promote_command(
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    config_path: Annotated[str, typer.Option("--config")] = "config/config.yaml",
) -> None:
    _, _, orchestrator = _bootstrap(config_path)
    result = orchestrator.promote_candidate(UUID(candidate_id))
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli()
