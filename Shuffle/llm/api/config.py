"""Application settings, loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    app_name: str = "AI Playbook Recommender"
    api_version: str = "v1"
    secret_key: str = "change-me-in-env"
    access_token_expire_minutes: int = 720

    # Database
    postgres_user: str = "playbook"
    postgres_password: str = "playbook"
    postgres_db: str = "playbooks"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Vector store
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "playbooks"

    # Models
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_dim: int = 1024
    enable_reranker: bool = True

    # LLM (Ollama)
    ollama_host: str = "http://ollama:11434"
    llm_model: str = "llama3.1:8b"
    llm_temperature: float = 0.1
    llm_max_retries: int = 3

    # Shuffle SOAR integration (first-class)
    shuffle_api_url: str = ""
    shuffle_api_key: str = ""
    shuffle_org_id: str = ""
    shuffle_verify_ssl: bool = False
    shuffle_offline_ok: bool = True
    shuffle_sync_interval_minutes: int = 30
    shuffle_environment: str = "Shuffle"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def shuffle_connected(self) -> bool:
        return bool(self.shuffle_api_url and self.shuffle_api_key)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
