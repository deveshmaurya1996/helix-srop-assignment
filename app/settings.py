"""Central config from environment / `.env`. See `.env.example` for all keys."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-in-prod"

    database_url: str = "sqlite+aiosqlite:///./helix_srop.db"
    chroma_persist_dir: str = "./chroma_db"

    google_api_key: str = ""  # copied into process env for ADK / Gemini (see adk_runner)
    adk_model: str = "gemini-2.0-flash"

    llm_timeout_seconds: int = 30  # pipeline + execute_turn wait_for
    tool_timeout_seconds: int = 10  # reserved for future tool-level caps

    idempotency_enabled: bool = True  # E1
    rerank_enabled: bool = True  # E4; search_docs oversamples then rerank_chunks
    rerank_oversample: int = 3
    guardrails_enabled: bool = True  # E5 pre-LLM gate


settings = Settings()
