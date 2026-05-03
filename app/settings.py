from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-in-prod"

    database_url: str = "sqlite+aiosqlite:///./helix_srop.db"
    chroma_persist_dir: str = "./chroma_db"

    google_api_key: str = ""
    adk_model: str = "gemini-2.0-flash"

    llm_timeout_seconds: int = 30
    tool_timeout_seconds: int = 10

    idempotency_enabled: bool = True
    rerank_enabled: bool = True
    rerank_oversample: int = 3
    guardrails_enabled: bool = True


settings = Settings()
