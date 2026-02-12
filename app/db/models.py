from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_segment: Mapped[str] = mapped_column(String(50), default="sme_enterprise")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    platform_accounts: Mapped[list["CompanyPlatformAccount"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    posts: Mapped[list["Post"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class CompanyCandidate(Base):
    __tablename__ = "company_candidates"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(500), nullable=False)
    platform_company_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source_keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("platform", "profile_url", name="uq_candidate_platform_profile"),)


class CompanyPlatformAccount(Base):
    __tablename__ = "company_platform_accounts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(500), nullable=False)
    platform_company_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_successful_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="platform_accounts")

    __table_args__ = (UniqueConstraint("company_id", "platform", name="uq_company_platform"),)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="all")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_profile_url: Mapped[str] = mapped_column(String(500), nullable=False)
    post_text: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), default="unknown")
    hashtags: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    links: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    cta_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    post_structure: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    metrics_provenance: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="posts")
    metric_snapshots: Mapped[list["PostMetricSnapshot"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("platform", "platform_post_id", name="uq_post_platform_postid"),
        Index("ix_posts_published_at", "published_at"),
        Index("ix_posts_company_id", "company_id"),
        Index("ix_posts_platform", "platform"),
        Index("ix_posts_media_type", "media_type"),
    )


class PostMetricSnapshot(Base):
    __tablename__ = "post_metric_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    post_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )

    post: Mapped["Post"] = relationship(back_populates="metric_snapshots")

    __table_args__ = (Index("ix_metric_post_captured_at", "post_id", "captured_at"),)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_markdown: Mapped[str] = mapped_column(Text, default="")
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    insights: Mapped[list["AnalysisInsight"]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan"
    )


class AnalysisInsight(Base):
    __tablename__ = "analysis_insights"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    insight_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="insights")


class GeneratedPost(Base):
    __tablename__ = "generated_posts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    cta: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    validation_flags: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    target_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index(
    "ix_analysis_insights_payload_gin",
    AnalysisInsight.payload,
    postgresql_using="gin",
)
