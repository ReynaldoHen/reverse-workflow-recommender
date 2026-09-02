import datetime as dt
from sqlalchemy import create_engine, String, Integer, DateTime, Text, JSON
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, sessionmaker)
from .config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Playbook(Base):
    __tablename__ = "playbooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    steps: Mapped[dict] = mapped_column(JSON)
    apps: Mapped[dict] = mapped_column(JSON)
    shuffle_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class GeneratedWorkflow(Base):
    __tablename__ = "generated_workflows"
    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    intermediate_json: Mapped[dict] = mapped_column(JSON)
    shuffle_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="generated")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    playbook_slug: Mapped[str] = mapped_column(String(120))
    helpful: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_models():
    Base.metadata.create_all(bind=engine)
