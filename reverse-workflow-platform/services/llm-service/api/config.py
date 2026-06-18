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
    # Read timeout for a single Ollama generation call (seconds).
    # llama3.1:8b on CPU can take 5–15 min for a complex prompt.
    # Override via OLLAMA_READ_TIMEOUT in .env — set lower if you have GPU.
    ollama_read_timeout: int = 900

    # Neo4j Aura (dibaca dari .env: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE)
    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: str = ""
    neo4j_database: str = ""

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
    def neo4j_auth(self) -> tuple[str, str]:
        """Tuple (username, password) untuk AsyncGraphDatabase.driver(auth=...)."""
        return (self.neo4j_username, self.neo4j_password)

    @property
    def shuffle_connected(self) -> bool:
        return bool(self.shuffle_api_url and self.shuffle_api_key)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()