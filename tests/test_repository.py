from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CompanyCandidate, CompanyPlatformAccount
from app.db.repository import Repository
from app.scrapers.base import CompanyCandidate as CandidateDTO
from app.scrapers.base import NormalizedPost


def test_repository_upsert_post():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with Session() as session:
        repo = Repository(session)
        repo.sync_companies_from_config(
            [
                {
                    "name": "Test Co",
                    "website": "https://example.com",
                    "linkedin_url": "https://www.linkedin.com/company/testco/",
                    "linkedin_company_id": "li-123",
                    "facebook_url": "https://www.facebook.com/testco",
                    "facebook_page_id": "fb-456",
                    "active": True,
                }
            ]
        )
        company_ref = repo.get_active_company_refs(platforms=["linkedin"])[0]
        assert company_ref.platform_company_id == "li-123"
        post = NormalizedPost(
            platform="linkedin",
            platform_post_id="post-1",
            company_id=company_ref.id,
            company_name=company_ref.name,
            company_profile_url=company_ref.profile_url,
            post_text="ERP modernization case study",
            published_at=datetime.now(timezone.utc),
            media_type="text",
            hashtags=["erp"],
            links=[],
            cta_text="learn more",
            post_structure={"char_count": 30},
            metrics={"likes": 10, "comments": 1, "shares": 1, "views": None},
            metrics_provenance={"likes": "api", "comments": "api", "shares": "api", "views": "unavailable"},
        )
        first_id = repo.upsert_post(post)
        second_id = repo.upsert_post(post)
        session.commit()
        assert first_id == second_id
        posts = repo.get_posts_for_analysis(window_days=365)
        assert len(posts) == 1


def test_candidate_activation_and_promotion():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with Session() as session:
        repo = Repository(session)
        candidate = CompanyCandidate(
            platform="linkedin",
            name="Acme ERP",
            profile_url="https://www.linkedin.com/company/acme-erp/",
            platform_company_id="999",
            confidence=0.8,
            source_keyword="erp",
            metadata_json={},
            active=False,
        )
        session.add(candidate)
        session.flush()

        repo.activate_candidate(candidate.id)
        assert candidate.active is True

        company_id = repo.promote_candidate_to_company(candidate.id)
        assert isinstance(company_id, UUID)
        account = session.query(CompanyPlatformAccount).filter_by(company_id=company_id, platform="linkedin").one()
        assert account.platform_company_id == "999"
        assert repo.count_active_companies() == 1


def test_upsert_candidate_returns_created_flag_and_auto_promotable():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with Session() as session:
        repo = Repository(session)
        candidate = CandidateDTO(
            platform="facebook",
            name="Acme Cloud",
            profile_url="https://www.facebook.com/acme",
            platform_company_id="fb-999",
            confidence=0.9,
            source_keyword="cloud",
            metadata={"source": "test"},
        )
        candidate_id_1, created_1 = repo.upsert_company_candidate(candidate)
        assert created_1 is True

        candidate.platform_company_id = "fb-1000"
        candidate_id_2, created_2 = repo.upsert_company_candidate(candidate)
        assert created_2 is False
        assert candidate_id_1 == candidate_id_2

        candidate_row = repo.get_candidate(candidate_id_1)
        assert candidate_row is not None
        assert Repository.is_candidate_auto_promotable(candidate_row, min_confidence=0.85) is True
        assert Repository.is_candidate_auto_promotable(candidate_row, min_confidence=0.95) is False


def test_analysis_run_and_generated_posts():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with Session() as session:
        repo = Repository(session)
        run = repo.create_analysis_run(window_days=90)
        repo.finish_analysis_run(run.id, "success", "ok", {"kpis": {"total_posts": 0}})
        repo.add_analysis_insight(run.id, "kpis", {"total_posts": 0})
        post_id = repo.save_generated_post(
            analysis_run_id=run.id,
            platform="linkedin",
            content="Test content",
            hashtags=["erp"],
            cta="book a demo",
            prompt_hash="abc123",
            model_name="rule-based",
            similarity_score=0.2,
            validation_flags=[],
        )
        session.commit()
        assert post_id is not None
        generated_df = repo.generated_posts_to_dataframe()
        assert len(generated_df) == 1
