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
    admin_username: str = "admin"
    admin_password: str = "admin"
    google_books_api_key: str | None = None
    google_oauth_client_id: str | None = None
    gravatar_oauth_client_id: str | None = None
    gravatar_oauth_client_secret: str | None = None
    resend_api_key: str | None = None
    resend_webhook_secret: str | None = None
    email_dry_run: bool = True
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expiry_minutes: int = 15
    refresh_token_expiry_days: int = 60
    mongodb_url: str
    mongodb_db_name: str
    redis_url: str
    club_ownership_action_rate_limit: int = 10
    club_ownership_action_rate_limit_window_seconds: int = 3600
    auth_register_rate_limit: int = 5
    auth_register_rate_limit_window_seconds: int = 3600
    auth_oauth_signin_rate_limit: int = 20
    auth_oauth_signin_rate_limit_window_seconds: int = 3600
    auth_login_ip_rate_limit: int = 20
    auth_login_account_rate_limit: int = 10
    auth_login_rate_limit_window_seconds: int = 900
    auth_refresh_rate_limit: int = 30
    auth_refresh_rate_limit_window_seconds: int = 60
    email_rate_limit: int = 5
    current_terms_version: int = 1
    current_privacy_version: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
