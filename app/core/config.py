from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformRateLimit(BaseModel):
    requests_per_minute: int = Field(default=30, ge=1)
    jitter_min_seconds: float = Field(default=0.5, ge=0)
    jitter_max_seconds: float = Field(default=2.0, ge=0)
    retry_max_attempts: int = Field(default=4, ge=1)
    retry_base_seconds: float = Field(default=1.0, ge=0.1)
    circuit_breaker_threshold: int = Field(default=5, ge=1)
    circuit_breaker_cooldown_seconds: int = Field(default=120, ge=1)


class RateLimitConfig(BaseModel):
    linkedin: PlatformRateLimit = Field(default_factory=PlatformRateLimit)
    facebook: PlatformRateLimit = Field(default_factory=PlatformRateLimit)
    fallback: PlatformRateLimit = Field(
        default_factory=lambda: PlatformRateLimit(requests_per_minute=12)
    )


class CompanyConfig(BaseModel):
    name: str
    website: str | None = None
    linkedin_url: str | None = None
    linkedin_company_id: str | None = None
    facebook_url: str | None = None
    facebook_page_id: str | None = None
    active: bool = True


class DiscoveryConfig(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    max_candidates_per_keyword: int = Field(default=20, ge=1, le=100)
    max_monitored_companies: int = Field(default=50, ge=1, le=500)
    auto_promote_enabled: bool = True
    auto_promote_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class ScrapeConfig(BaseModel):
    backfill_days: int = Field(default=90, ge=1, le=730)
    lookback_hours_on_incremental: int = Field(default=4, ge=0, le=48)
    default_platforms: list[str] = Field(default_factory=lambda: ["linkedin", "facebook"])
    include_playwright_fallback: bool = True
    allow_fallback_without_platform_id: bool = True
    user_agent: str = "socialintel-bot/0.1 (+compliant-public-collection)"
    navigation_timeout_seconds: int = Field(default=30, ge=5, le=120)


class GenerationConfig(BaseModel):
    default_count: int = Field(default=12, ge=1, le=50)
    min_themes: int = Field(default=4, ge=1, le=10)
    max_similarity_threshold: float = Field(default=0.82, ge=0.3, le=0.98)
    default_language: str = "en"
    style: str = "B2B thought leadership"
    linkedin_ratio: float = Field(default=0.5, ge=0.1, le=0.9)


class SchedulerConfig(BaseModel):
    timezone: str = "UTC"
    discover_cron: str = "0 1 * * *"
    scrape_cron: str = "0 2 * * *"
    analyze_cron: str = "0 3 * * *"
    generate_cron: str = "30 3 * * *"


class ExportConfig(BaseModel):
    default_formats: list[str] = Field(default_factory=lambda: ["csv", "json", "xlsx"])
    output_dir: str = "exports"


class WebUIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    editable_config_path: str = "config/config.yaml"


class NotificationConfig(BaseModel):
    webhook_enabled: bool = True
    webhook_timeout_seconds: int = Field(default=10, ge=1, le=60)


class AppConfig(BaseModel):
    environment: str = "local"
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    companies: list[CompanyConfig] = Field(default_factory=list)
    scrape: ScrapeConfig = Field(default_factory=ScrapeConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    web_ui: WebUIConfig = Field(default_factory=WebUIConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid config file '{config_path}': {exc}") from exc

    def to_editable_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        return data


class SecretSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/socialintel"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_access_token: str = ""
    linkedin_refresh_token: str = ""

    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    facebook_access_token: str = ""
    facebook_refresh_token: str = ""

    webhook_url: str = ""


class Settings(BaseModel):
    config: AppConfig
    secrets: SecretSettings


def write_config(path: str | Path, config: AppConfig) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config.model_dump(), handle, sort_keys=False)


@lru_cache(maxsize=1)
def load_settings(config_path: str = "config/config.yaml") -> Settings:
    config = AppConfig.from_yaml(config_path)
    secrets = SecretSettings()
    return Settings(config=config, secrets=secrets)


def reset_settings_cache() -> None:
    load_settings.cache_clear()
