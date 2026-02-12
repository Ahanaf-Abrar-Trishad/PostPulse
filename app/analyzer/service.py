from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.logging import get_logger
from app.db.models import Post

logger = get_logger(__name__)


@dataclass
class AnalysisResult:
    summary_markdown: str
    summary_json: dict[str, Any]
    insights: list[tuple[str, dict[str, Any]]]


class AnalyzerService:
    def analyze_posts(self, posts: list[Post], window_days: int) -> AnalysisResult:
        if not posts:
            empty_summary = "No posts available in the analysis window."
            return AnalysisResult(
                summary_markdown=empty_summary,
                summary_json={"kpis": {}, "insights": []},
                insights=[],
            )

        df = self._to_dataframe(posts)
        df["engagement_total"] = (
            df[["likes", "comments", "shares", "views"]]
            .fillna(0)
            .sum(axis=1)
        )
        df["engagement_score"] = self._normalized_engagement(df)

        top_decile_threshold = float(df["engagement_score"].quantile(0.9))
        top_posts = df[df["engagement_score"] >= top_decile_threshold].copy()
        if top_posts.empty:
            top_posts = df.nlargest(max(1, int(len(df) * 0.1)), "engagement_score")

        media_stats = self._media_stats(df)
        posting_time_heatmap = self._posting_time_heatmap(df)
        hashtag_stats = self._hashtag_effectiveness(df)
        cta_stats = self._cta_effectiveness(df)
        themes = self._extract_themes(df["post_text"].fillna("").tolist())
        patterns = self._extract_patterns(top_posts)

        insights: list[tuple[str, dict[str, Any]]] = [
            ("kpis", self._kpis(df)),
            ("media_stats", media_stats),
            ("posting_time_heatmap", posting_time_heatmap),
            ("hashtag_effectiveness", hashtag_stats),
            ("cta_effectiveness", cta_stats),
            ("themes", themes),
            ("high_performing_patterns", patterns),
        ]

        summary_json = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": window_days,
            "kpis": self._kpis(df),
            "top_slots": posting_time_heatmap.get("top_slots", []),
            "top_hashtags": hashtag_stats.get("top_hashtags", []),
            "top_cta_phrases": cta_stats.get("top_ctas", []),
            "themes": themes.get("themes", []),
            "patterns": patterns,
        }
        summary_markdown = self._summary_markdown(summary_json)

        return AnalysisResult(
            summary_markdown=summary_markdown,
            summary_json=summary_json,
            insights=insights,
        )

    @staticmethod
    def _to_dataframe(posts: list[Post]) -> pd.DataFrame:
        rows = []
        for post in posts:
            metrics = post.metrics or {}
            rows.append(
                {
                    "id": str(post.id),
                    "platform": post.platform,
                    "company_name": post.company_name,
                    "published_at": post.published_at,
                    "media_type": post.media_type,
                    "post_text": post.post_text or "",
                    "hashtags": post.hashtags or [],
                    "cta_text": post.cta_text,
                    "likes": metrics.get("likes"),
                    "comments": metrics.get("comments"),
                    "shares": metrics.get("shares"),
                    "views": metrics.get("views"),
                    "char_count": (post.post_structure or {}).get("char_count", len(post.post_text or "")),
                }
            )
        df = pd.DataFrame(rows)
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
        df["weekday"] = df["published_at"].dt.day_name()
        df["hour"] = df["published_at"].dt.hour
        return df

    @staticmethod
    def _normalized_engagement(df: pd.DataFrame) -> pd.Series:
        totals = df[["likes", "comments", "shares", "views"]].fillna(0).sum(axis=1).astype(float)
        if float(totals.max()) == float(totals.min()):
            return pd.Series(np.ones(len(df)), index=df.index)
        return (totals - totals.min()) / (totals.max() - totals.min() + 1e-9)

    @staticmethod
    def _kpis(df: pd.DataFrame) -> dict[str, Any]:
        grouped = df.groupby("platform")["engagement_total"].agg(["mean", "median", "max", "count"])
        return {
            "total_posts": int(len(df)),
            "by_platform": grouped.round(3).to_dict(orient="index"),
            "avg_engagement": float(df["engagement_total"].mean()),
            "median_engagement": float(df["engagement_total"].median()),
        }

    @staticmethod
    def _media_stats(df: pd.DataFrame) -> dict[str, Any]:
        media = (
            df.groupby("media_type")["engagement_total"]
            .agg(["count", "mean", "median", "max"])
            .sort_values("mean", ascending=False)
        )
        return {"rows": media.round(3).reset_index().to_dict(orient="records")}

    @staticmethod
    def _posting_time_heatmap(df: pd.DataFrame) -> dict[str, Any]:
        table = (
            df.groupby(["weekday", "hour"])["engagement_total"]
            .mean()
            .reset_index()
            .sort_values("engagement_total", ascending=False)
        )
        top_slots = table.head(10).to_dict(orient="records")
        return {"top_slots": top_slots}

    @staticmethod
    def _hashtag_effectiveness(df: pd.DataFrame) -> dict[str, Any]:
        exploded = df.explode("hashtags")
        exploded = exploded[exploded["hashtags"].notna() & (exploded["hashtags"] != "")]
        if exploded.empty:
            return {"top_hashtags": []}
        stats = (
            exploded.groupby("hashtags")["engagement_total"]
            .agg(["count", "median", "mean"])
            .query("count >= 2")
            .sort_values("median", ascending=False)
            .head(20)
        )
        return {"top_hashtags": stats.reset_index().to_dict(orient="records")}

    @staticmethod
    def _cta_effectiveness(df: pd.DataFrame) -> dict[str, Any]:
        cta_df = df[df["cta_text"].notna() & (df["cta_text"] != "")]
        if cta_df.empty:
            return {"top_ctas": []}
        stats = (
            cta_df.groupby("cta_text")["engagement_total"]
            .agg(["count", "median", "mean"])
            .query("count >= 2")
            .sort_values("median", ascending=False)
            .head(20)
        )
        return {"top_ctas": stats.reset_index().to_dict(orient="records")}

    def _extract_themes(self, texts: list[str]) -> dict[str, Any]:
        cleaned = [text.strip() for text in texts if text and len(text.split()) >= 3]
        if len(cleaned) < 5:
            return {"themes": []}
        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=2000,
            ngram_range=(1, 2),
            min_df=2,
        )
        matrix = vectorizer.fit_transform(cleaned)
        topic_count = min(6, max(2, int(matrix.shape[0] / 20)))
        model = NMF(n_components=topic_count, init="nndsvda", random_state=7, max_iter=400)
        topic_matrix = model.fit_transform(matrix)
        vocab = np.array(vectorizer.get_feature_names_out())
        themes: list[dict[str, Any]] = []
        for i, topic in enumerate(model.components_):
            term_indices = topic.argsort()[-8:][::-1]
            terms = vocab[term_indices].tolist()
            theme_strength = float(topic_matrix[:, i].mean())
            themes.append({"topic_id": i + 1, "terms": terms, "strength": round(theme_strength, 4)})
        themes.sort(key=lambda item: item["strength"], reverse=True)
        return {"themes": themes}

    @staticmethod
    def _extract_patterns(top_posts: pd.DataFrame) -> dict[str, Any]:
        if top_posts.empty:
            return {}
        char_bins = pd.cut(
            top_posts["char_count"].fillna(0),
            bins=[-1, 150, 450, 2000, 10000],
            labels=["short", "medium", "long", "very_long"],
        )
        by_length = (
            top_posts.assign(length_band=char_bins)
            .groupby("length_band")["engagement_total"]
            .agg(["count", "median"])
            .sort_values("median", ascending=False)
            .reset_index()
            .to_dict(orient="records")
        )
        by_media = (
            top_posts.groupby("media_type")["engagement_total"]
            .agg(["count", "median"])
            .sort_values("median", ascending=False)
            .reset_index()
            .to_dict(orient="records")
        )
        hashtag_counts = top_posts["hashtags"].map(len).describe().to_dict()
        return {
            "length_bands": by_length,
            "media_types": by_media,
            "hashtag_count_distribution": {k: float(v) for k, v in hashtag_counts.items()},
        }

    @staticmethod
    def _summary_markdown(summary_json: dict[str, Any]) -> str:
        lines = [
            "# Social Intelligence Summary",
            "",
            f"- Window days: {summary_json['window_days']}",
            f"- Total posts analyzed: {summary_json['kpis'].get('total_posts', 0)}",
            f"- Average engagement: {summary_json['kpis'].get('avg_engagement', 0):.2f}",
            "",
            "## Top Posting Slots",
        ]
        for row in summary_json.get("top_slots", [])[:5]:
            lines.append(
                f"- {row.get('weekday')} @ {int(row.get('hour', 0)):02d}:00 -> {row.get('engagement_total', 0):.2f}"
            )
        lines.append("")
        lines.append("## Top Hashtags")
        for row in summary_json.get("top_hashtags", [])[:8]:
            lines.append(
                f"- #{row.get('hashtags')} (median engagement {row.get('median', 0):.2f}, n={row.get('count', 0)})"
            )
        lines.append("")
        lines.append("## Themes")
        for theme in summary_json.get("themes", [])[:4]:
            lines.append(f"- Topic {theme['topic_id']}: {', '.join(theme['terms'][:5])}")
        return "\n".join(lines)
