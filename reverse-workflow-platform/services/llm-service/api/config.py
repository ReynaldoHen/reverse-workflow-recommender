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

    # LLM (Ollama)
    ollama_host: str = "http://ollama:11434"
    llm_model: str = "dengcao/Qwen3-8B:Q5_K_M"
    llm_temperature: float = 0.3
    llm_think: bool = False
    llm_top_p: float = 0.95
    llm_top_k: int = 20
    llm_presence_penalty: float = 1.5
    llm_num_predict: int = 1536
    llm_num_ctx: int = 4096
    llm_format: str = "json"
    llm_max_retries: int = 3
    ollama_read_timeout: int = 900

    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: str = ""
    neo4j_database: str = ""

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