from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

HASHTAG_PATTERN = re.compile(r"#([A-Za-z0-9_]+)")
URL_PATTERN = re.compile(r"(https?://[^\s]+)")
CTA_PATTERN = re.compile(
    r"\b(book a demo|contact us|get started|learn more|schedule a call|download now|sign up|talk to us)\b",
    flags=re.IGNORECASE,
)

MediaType = Literal["text", "image", "video", "carousel", "document", "mixed", "unknown"]


@dataclass(slots=True)
class CompanyRef:
    id: UUID
    name: str
    profile_url: str
    platform: Literal["linkedin", "facebook"]
    platform_company_id: str | None = None


@dataclass(slots=True)
class CompanyCandidate:
    platform: Literal["linkedin", "facebook"]
    name: str
    profile_url: str
    platform_company_id: str | None
    confidence: float
    source_keyword: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class RawPost:
    post_id: str
    text: str
    published_at: datetime
    media_type: MediaType
    metrics: dict[str, int | None]
    metadata: dict[str, Any]


@dataclass(slots=True)
class NormalizedPost:
    platform: str
    platform_post_id: str
    company_id: UUID
    company_name: str
    company_profile_url: str
    post_text: str
    published_at: datetime
    media_type: MediaType
    hashtags: list[str]
    links: list[str]
    cta_text: str | None
    post_structure: dict[str, Any]
    metrics: dict[str, int | None]
    metrics_provenance: dict[str, Literal["api", "scrape", "unavailable"]]


class BaseCollector(Protocol):
    platform: Literal["linkedin", "facebook"]

    def authenticate(self) -> None: ...

    def discover_companies(self, keywords: list[str]) -> list[CompanyCandidate]: ...

    def fetch_posts(
        self, company: CompanyRef, since: datetime, until: datetime
    ) -> list[RawPost]: ...

    def normalize(self, raw: RawPost, company: CompanyRef) -> NormalizedPost: ...


def extract_hashtags(text: str) -> list[str]:
    return sorted({match.group(1).lower() for match in HASHTAG_PATTERN.finditer(text or "")})


def extract_links(text: str) -> list[str]:
    return sorted({match.group(1).strip(".,)") for match in URL_PATTERN.finditer(text or "")})


def extract_cta_text(text: str) -> str | None:
    match = CTA_PATTERN.search(text or "")
    if not match:
        return None
    return match.group(1).lower()


def infer_post_structure(text: str) -> dict[str, Any]:
    text = text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sentence_count = len([part for part in re.split(r"[.!?]", text) if part.strip()])
    return {
        "char_count": len(text),
        "line_count": len(lines),
        "sentence_count": sentence_count,
        "starts_with_question": text.strip().startswith("?"),
        "has_bullets": any(line.startswith(("-", "*", "1.")) for line in lines),
    }


def metrics_provenance(metrics: dict[str, int | None], source: str) -> dict[str, str]:
    provenance: dict[str, str] = {}
    for key, value in metrics.items():
        provenance[key] = source if value is not None else "unavailable"
    return provenance
