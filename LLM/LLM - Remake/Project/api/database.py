import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.postgres_url,
    echo=settings.app_env == "development",
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ── ORM Models ────────────────────────────────────────────────────────────────

class Playbook(Base):
    __tablename__ = "playbooks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(500), nullable=False)
    description = Column(Text)
    use_cases = Column(ARRAY(Text), default=[])
    integrations = Column(ARRAY(Text), default=[])
    triggers = Column(ARRAY(Text), default=[])
    tags = Column(ARRAY(Text), default=[])
    category = Column(String(100))
    shuffle_workflow_id = Column(String(100))
    shuffle_json = Column(JSONB, default={})
    confidence_threshold = Column(Float, default=0.75)
    qdrant_point_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_from_shuffle = Column(DateTime)
    is_active = Column(Boolean, default=True)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False)
    session_id = Column(String(100))
    recommended_playbook_id = Column(String(36))
    confidence_score = Column(Float)
    accepted = Column(Boolean)
    analyst_id = Column(String(100))
    intent = Column(String(50))
    use_refinement = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(100), primary_key=True)
    analyst_id = Column(String(100))
    conversation_history = Column(JSONB, default=[])
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    api_key = Column(String(64), unique=True)
    is_active = Column(Boolean, default=True)
    role = Column(String(20), default="analyst")
    created_at = Column(DateTime, default=datetime.utcnow)


# ── DB dependency ─────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
