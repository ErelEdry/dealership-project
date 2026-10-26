from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    environment: str = "development"
    debug:       bool = False   # True echoes every SQL statement (database.py)
    secret_key:  str = "changeme"
    # Required in the X-Admin-Token header for admin-only endpoints (the
    # bookings listing). Empty = those endpoints are disabled.
    admin_token: str = ""

    # Browser origins allowed by CORS, comma-separated
    # (e.g. "http://localhost:3000,https://cars.example.com").
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Database
    database_url: str = "postgresql+asyncpg://postgres:changeme@localhost:5432/dealership"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_host:       str = "localhost"
    qdrant_port:       int = 6333
    qdrant_collection: str = "vehicles_v1"

    # Groq (enrichment — free tier)
    # NOTE: the llama-3.x models were retired by Groq; gpt-oss-20b is the
    # current drop-in that returns valid JSON with our existing prompt.
    groq_api_key:      str = ""
    groq_chat_model:   str = "openai/gpt-oss-20b"

    # Embeddings (local via FastEmbed — no API key needed)
    embedding_model:      str = "BAAI/bge-base-en-v1.5"
    embedding_dimensions: int = 768
    embedding_cache_dir:  str = "/opt/fastembed_cache"   # named volume, survives recreate

    # Cohere (Phase 3 — reranking)
    cohere_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
