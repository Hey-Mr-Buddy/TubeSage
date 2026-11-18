from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Next.js reads .env.local; load it here too so FastAPI receives the same
    # Clerk and Supabase server credentials during local development. Explicit
    # process environment variables still take precedence over either file.
    model_config = SettingsConfigDict(env_file=(".env.local", ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "TubeSage"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_embedding_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    supabase_url: str = Field(default="", validation_alias=AliasChoices("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"))
    supabase_service_role_key: str = ""
    clerk_secret_key: str = ""
    evals_enabled: bool = True
    anthropic_eval_model: str = ""
    gemini_eval_model: str = ""
    database_path: str = "data/tubesage.sqlite3"
    # SaaS tier limits are enforced by the authenticated Next.js preflight.
    # Keep only a defensive platform ceiling here for transcription resources.
    max_video_minutes: int = 1440
    max_chat_messages_per_minute: int = 20
    transcript_languages: str = "en,en-US,en-GB"

    @property
    def primary_eval_model(self) -> str:
        return self.anthropic_eval_model or self.anthropic_model

    @property
    def fallback_eval_model(self) -> str:
        return self.gemini_eval_model or self.gemini_model

    @property
    def language_list(self) -> list[str]:
        return [item.strip() for item in self.transcript_languages.split(",") if item.strip()]

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cloud_mode(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
