from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from openai import OpenAI

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GeneratedContent:
    platform: str
    content: str
    hashtags: list[str]
    cta: str | None
    prompt_hash: str
    model_name: str
    similarity_score: float
    validation_flags: list[str]


class ContentGeneratorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name = settings.secrets.openai_model
        self.client = OpenAI(api_key=settings.secrets.openai_api_key) if settings.secrets.openai_api_key else None

    def generate_posts(
        self,
        insights: dict[str, Any],
        source_texts: list[str],
        count: int,
        platforms: list[str],
        language: str = "en",
    ) -> list[GeneratedContent]:
        count = max(1, count)
        platform_plan = self._platform_distribution(count, platforms)
        generated: list[GeneratedContent] = []
        popular_hashtags = [
            row.get("hashtags")
            for row in insights.get("top_hashtags", [])
            if row.get("hashtags")
        ][:10]
        themes = [theme.get("terms", []) for theme in insights.get("themes", []) if theme.get("terms")]
        while len(themes) < self.settings.config.generation.min_themes:
            themes.append(["erp", "automation", "cloud", "transformation"])

        for platform, platform_count in platform_plan.items():
            for idx in range(platform_count):
                theme_terms = themes[idx % len(themes)]
                prompt = self._build_prompt(
                    platform=platform,
                    language=language,
                    style=self.settings.config.generation.style,
                    theme_terms=theme_terms,
                    insight_json=insights,
                    popular_hashtags=popular_hashtags,
                )
                prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                content_payload = self._generate_single(prompt)
                content = content_payload["content"].strip()
                hashtags = content_payload.get("hashtags", [])
                cta = content_payload.get("cta")
                score = self._max_similarity(content, source_texts)
                flags: list[str] = []
                if score >= self.settings.config.generation.max_similarity_threshold:
                    flags.append("high_similarity")
                    content = self._regenerate_with_constraint(prompt, source_texts)
                    score = self._max_similarity(content, source_texts)
                if len(hashtags) < 2:
                    flags.append("low_hashtag_count")
                generated.append(
                    GeneratedContent(
                        platform=platform,
                        content=content,
                        hashtags=hashtags,
                        cta=cta,
                        prompt_hash=prompt_hash,
                        model_name=self.model_name if self.client else "rule-based",
                        similarity_score=score,
                        validation_flags=flags,
                    )
                )
        return generated

    def _generate_single(self, prompt: str) -> dict[str, Any]:
        if not self.client:
            return self._rule_based_output(prompt)
        try:
            response = self.client.responses.create(
                model=self.model_name,
                input=prompt,
                temperature=0.8,
            )
            text = response.output_text.strip()
            return self._coerce_json(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI generation failed, using fallback template: %s", exc)
            return self._rule_based_output(prompt)

    def _regenerate_with_constraint(self, prompt: str, source_texts: list[str]) -> str:
        if not self.client:
            fallback = self._rule_based_output(prompt)["content"]
            return fallback
        constrained_prompt = (
            prompt
            + "\n\nRegenerate with clearly different sentence structure and angle. "
            + "Avoid close paraphrasing of known examples."
        )
        for _ in range(2):
            payload = self._generate_single(constrained_prompt)
            content = payload["content"].strip()
            if self._max_similarity(content, source_texts) < self.settings.config.generation.max_similarity_threshold:
                return content
        return self._generate_single(constrained_prompt)["content"].strip()

    def _platform_distribution(self, count: int, platforms: list[str]) -> dict[str, int]:
        normalized = [platform.lower() for platform in platforms] or ["linkedin", "facebook"]
        unique_platforms = list(dict.fromkeys(normalized))
        supported = {"linkedin", "facebook"}
        invalid = [item for item in unique_platforms if item not in supported]
        if invalid:
            raise ValueError(f"Unsupported platform(s): {', '.join(invalid)}")
        if len(unique_platforms) == 1:
            return {unique_platforms[0]: count}

        ratio = self.settings.config.generation.linkedin_ratio
        linkedin_count = int(round(count * ratio))
        linkedin_count = max(1, min(count - 1, linkedin_count))
        return {"linkedin": linkedin_count, "facebook": count - linkedin_count}

    @staticmethod
    def _build_prompt(
        platform: str,
        language: str,
        style: str,
        theme_terms: list[str],
        insight_json: dict[str, Any],
        popular_hashtags: list[str],
    ) -> str:
        rules = {
            "linkedin": "Professional B2B tone, clear strategic takeaway, concise CTA.",
            "facebook": "Conversational but expert tone, approachable and value-first CTA.",
        }[platform]
        payload = {
            "instruction": "Return strict JSON with keys: content, hashtags (array), cta.",
            "platform": platform,
            "language": language,
            "style": style,
            "platform_rules": rules,
            "theme_terms": theme_terms,
            "popular_hashtags": popular_hashtags[:8],
            "insights": {
                "top_slots": insight_json.get("top_slots", [])[:5],
                "top_hashtags": insight_json.get("top_hashtags", [])[:10],
                "top_cta_phrases": insight_json.get("top_cta_phrases", [])[:6],
            },
            "constraints": [
                "Original text, no plagiarism.",
                "Include a clear CTA.",
                "Use 3-7 hashtags.",
                "No markdown formatting.",
            ],
        }
        return json.dumps(payload, ensure_ascii=True)

    @staticmethod
    def _coerce_json(raw_text: str) -> dict[str, Any]:
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:].strip()
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return {
                "content": raw_text,
                "hashtags": [],
                "cta": None,
            }
        return {
            "content": str(data.get("content", "")).strip(),
            "hashtags": [str(tag).lstrip("#").lower() for tag in data.get("hashtags", []) if tag],
            "cta": str(data.get("cta", "")).strip() or None,
        }

    @staticmethod
    def _rule_based_output(prompt: str) -> dict[str, Any]:
        base_messages = [
            "ERP projects fail when teams optimize tools before outcomes.",
            "Digital transformation succeeds when leadership aligns process, data, and change ownership.",
            "Cloud ROI increases when migration roadmaps include measurable business checkpoints.",
        ]
        ctas = ["Book a discovery call", "Request an architecture review", "Talk to our consultants"]
        hashtags = ["erp", "digitaltransformation", "odoo", "cloudstrategy", "businessautomation"]
        content = f"{random.choice(base_messages)} Focus on one high-impact workflow this quarter."
        return {"content": content, "hashtags": hashtags[:4], "cta": random.choice(ctas)}

    @staticmethod
    def _max_similarity(candidate: str, source_texts: list[str]) -> float:
        if not source_texts or not candidate:
            return 0.0
        candidate = candidate.strip().lower()
        scores = [
            SequenceMatcher(a=candidate, b=(text or "").strip().lower()).ratio()
            for text in source_texts[:1000]
        ]
        return float(max(scores)) if scores else 0.0
