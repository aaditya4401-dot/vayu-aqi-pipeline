"""Database connection manager for the Vayu pipeline.

Loads DATABASE_URL from .env, creates engine + session factory.
Falls back to SQLite if PostgreSQL is unavailable.
"""

import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()
logger = logging.getLogger(__name__)

# Module-level singletons (initialized lazily)
_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _build_postgres_url() -> str:
    """Construct PostgreSQL URL from individual env vars or DATABASE_URL."""
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "vayu")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


SQLITE_URL = "sqlite:///vayu.db"


def get_engine(force_new: bool = False) -> Engine:
    """Get or create the SQLAlchemy engine.

    Tries PostgreSQL first. If the connection fails, falls back to SQLite
    so the pipeline can still run for development and demos.

    Args:
        force_new: If True, discard any existing engine and create a fresh one.

    Returns:
        A connected SQLAlchemy Engine.
    """
    global _engine

    if _engine is not None and not force_new:
        return _engine

    pg_url = _build_postgres_url()

    # Try PostgreSQL
    try:
        engine = create_engine(
            pg_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        # Verify connection actually works
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Connected to PostgreSQL: %s", pg_url.split("@")[-1])
        _engine = engine
        return _engine
    except Exception as exc:
        logger.warning("PostgreSQL connection failed: %s", exc)
        logger.info("Falling back to SQLite: %s", SQLITE_URL)

    # Fallback to SQLite
    _engine = create_engine(SQLITE_URL, echo=False)
    logger.info("Connected to SQLite: %s", SQLITE_URL)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get or create a session factory bound to the current engine."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory


def get_session() -> Session:
    """Create a new database session.

    Usage::

        session = get_session()
        try:
            # ... do work ...
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    """
    factory = get_session_factory()
    return factory()


def is_postgres() -> bool:
    """Check whether the active engine is PostgreSQL (vs SQLite fallback)."""
    engine = get_engine()
    return engine.dialect.name == "postgresql"


def reset() -> None:
    """Reset the module-level engine and session factory.

    Useful for testing or reconnecting after config change.
    """
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
