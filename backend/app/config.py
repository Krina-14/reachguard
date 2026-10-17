"""
ReachGuard application settings.

Reads every environment variable defined in the shared contract (Section 2).
In APP_ENV=prod, refuses to start if JWT_SECRET is empty/short or FALKORDB_PASSWORD is empty.
"""

from __future__ import annotations

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ── Application ──────────────────────────────────────────
    APP_ENV: str = "dev"

    # ── FalkorDB ─────────────────────────────────────────────
    FALKORDB_HOST: str = "localhost"
    FALKORDB_PORT: int = 6379
    FALKORDB_PASSWORD: str = ""
    GRAPH_PREFIX: str = "rg"

    # ── Authentication ───────────────────────────────────────
    JWT_SECRET: str = ""
    JWT_EXPIRE_MINUTES: int = 60

    # ── Bootstrap admin ──────────────────────────────────────
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # ── CORS ─────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:5173"

    # ── Ingestion ────────────────────────────────────────────
    WORK_DIR: str = "/tmp/reachguard"
    MAX_REPO_MB: int = 100
    MAX_ZIP_MB: int = 50
    MAX_PY_FILES: int = 5000

    # ── OSV ──────────────────────────────────────────────────
    OSV_BASE_URL: str = "https://api.osv.dev"
    OSV_CACHE_DIR: str = "/data/osv_cache"

    # ── LLM ──────────────────────────────────────────────────
    LLM_PROVIDER: str = "ollama"
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "qwen2.5:7b-instruct"
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_S: int = 60

    # ── Computed helpers ─────────────────────────────────────

    @property
    def cors_origin_list(self) -> list[str]:
        """Split CORS_ORIGINS into a list."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV == "prod"

    # ── Validators ───────────────────────────────────────────

    @field_validator("APP_ENV")
    @classmethod
    def _validate_app_env(cls, v: str) -> str:
        if v not in ("dev", "prod"):
            raise ValueError("APP_ENV must be 'dev' or 'prod'")
        return v

    @model_validator(mode="after")
    def _enforce_prod_requirements(self) -> Settings:
        """In prod, certain secrets are mandatory."""
        if self.APP_ENV != "prod":
            return self

        if not self.JWT_SECRET or len(self.JWT_SECRET) < 32:
            raise ValueError(
                "JWT_SECRET must be set and at least 32 characters in prod"
            )

        if not self.FALKORDB_PASSWORD:
            raise ValueError("FALKORDB_PASSWORD must be set in prod")

        return self


settings = Settings()
