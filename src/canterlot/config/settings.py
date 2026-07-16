from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from .enums import Environment


class Settings(BaseSettings):
    environment: Environment = Environment.LOCAL
    cors_origins: list[str] = [
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    google_books_api_key: str
    google_oauth_client_id: str | None = None
    gravatar_oauth_client_id: str | None = None
    gravatar_oauth_client_secret: str | None = None
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expiry_minutes: int = 15
    refresh_token_expiry_days: int = 60
    mongodb_url: str
    mongodb_db_name: str
    redis_url: str
    club_ownership_action_rate_limit: int = 10
    club_ownership_action_rate_limit_window_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
