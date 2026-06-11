from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Playbook Recommender"
    app_version: str = "3.0.0"
    app_env: str = "production"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8080"

    # ── Database ─────────────────────────────────────────────────────────────
    postgres_url: str = "postgresql+asyncpg://pbuser:pbpass@postgres:5432/playbooks"

    # ── Qdrant ───────────────────────────────────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection_playbooks: str = "playbooks"
    qdrant_collection_actions: str = "playbook_actions"
    qdrant_vector_size: int = 1024  # BGE-M3 dense dim

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: int = 120

    # ── Auth ──────────────────────────────────────────────────────────────────
    secret_key: str = "change-this-to-a-secure-random-string-minimum-32-chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # ── Shuffle ───────────────────────────────────────────────────────────────
    shuffle_api_url: str = ""
    shuffle_api_key: str = ""
    shuffle_sync_interval_minutes: int = 30

    # ── App Registry ──────────────────────────────────────────────────────────
    app_registry_path: str = "/tmp/shuffle_app_registry.json"  # persisted after Shuffle sync

    # ── Retrieval ─────────────────────────────────────────────────────────────
    semantic_weight: float = 0.5
    metadata_weight: float = 0.3
    keyword_weight: float = 0.2
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    confidence_low_threshold: float = 0.3
    confidence_warn_threshold: float = 0.5

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
