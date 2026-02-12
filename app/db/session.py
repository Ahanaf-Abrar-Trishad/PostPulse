from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Base


def create_engine_from_settings(settings: Settings):
    return create_engine(settings.secrets.database_url, pool_pre_ping=True)


def get_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine_from_settings(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(settings: Settings) -> None:
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
