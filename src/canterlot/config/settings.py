import os
from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from .enums import Environment

# ==============================================================================
# --- NESTED CONFIGURATION DOMAINS ---
# ==============================================================================


class AuthSettings(BaseModel):
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expiry_minutes: int = 15
    refresh_token_expiry_days: int = 60
    reset_token_expiry_minutes: int = 10
    verification_password_reset_ttl_minutes: int = 10
    verification_email_ttl_minutes: int = 15
    max_verification_attempts: int = 5
    current_terms_version: int = 1
    current_privacy_version: int = 1


class EmailSettings(BaseModel):
    dry_run: bool = True
    dispatch_max_rps: int = 5
    resend_api_key: SecretStr | None = None
    resend_webhook_secret: SecretStr | None = None


class DatabaseSettings(BaseModel):
    mongodb_url: SecretStr
    mongodb_db_name: str
    redis_url: SecretStr


class RateLimitSettings(BaseModel):
    # Club ownership limits
    club_ownership_action: int = 10
    club_ownership_action_window_seconds: int = 3600
    club_ownership_reclaim_window_hours: int = 24
    club_ownership_transfer_cooldown_days: int = 30

    # Club moderation limits
    club_moderation_action: int = 30
    club_moderation_action_window_seconds: int = 600

    # Auth & Session limits
    auth_register: int = 5
    auth_register_window_seconds: int = 3600

    auth_oauth_signin: int = 20
    auth_oauth_signin_window_seconds: int = 3600

    auth_login_ip: int = 20
    auth_login_account: int = 10
    auth_login_window_seconds: int = 900

    auth_refresh: int = 30
    auth_refresh_window_seconds: int = 60

    # Invites limit
    invite_create_direct: int = 10
    invite_create_direct_window_seconds: int = 3600

    # Password Mutations
    password_change: int = 5
    password_change_window_seconds: int = 3600

    # Password Reset Requests
    password_reset_request: int = 3
    password_reset_request_window_seconds: int = 3600

    password_reset_validate: int = 10
    password_reset_validate_window_seconds: int = 60

    # Email Verification Limits
    email_verification_request: int = 3
    email_verification_request_window_seconds: int = 3600

    email_verification_confirm: int = 10
    email_verification_confirm_window_seconds: int = 60

    # OAuth Provider Mutations
    provider_mutation: int = 5
    provider_mutation_window_seconds: int = 3600


class GatewaySettings(BaseModel):
    google_books_api_key: SecretStr | None = None
    google_oauth_client_id: str | None = None
    gravatar_oauth_client_id: str | None = None
    gravatar_oauth_client_secret: SecretStr | None = None


# ==============================================================================
# --- MAIN APPLICATION SETTINGS ---
# ==============================================================================


class Settings(BaseSettings):
    environment: Environment = Environment.LOCAL
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8080"
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("admin")

    auth: AuthSettings
    email: EmailSettings = Field(default_factory=EmailSettings)
    db: DatabaseSettings
    ratelimit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    gateways: GatewaySettings = Field(default_factory=GatewaySettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],  # noqa: ARG003
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        if os.getenv("ENVIRONMENT") == Environment.TEST:
            return (init_settings, env_settings, file_secret_settings)
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
