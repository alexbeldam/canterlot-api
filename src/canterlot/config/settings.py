from pydantic_settings import BaseSettings, SettingsConfigDict

from .enums import Environment


class Settings(BaseSettings):
    environment: Environment = Environment.LOCAL
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    google_books_api_key: str
    jwt_secret_key: str
    jwt_algorithm: str
    mongodb_url: str
    mongodb_db_name: str
    redis_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()  # pyright: ignore[reportCallIssue]
