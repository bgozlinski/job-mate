"""Settings read from the environment."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Every value the application reads from its environment.

    Values come from real environment variables first and from .env second,
    which is what lets the container and CI supply them without a file. The
    secrets are SecretStr so that a repr or a traceback cannot spill them
    into a log (NFR-1).

    The two provider keys are optional because CI has no keys and must
    still be able to import the application and run the suite; the clients
    are what fail, and only when something actually asks them to work.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str
    postgres_port: int

    redis_url: str

    openai_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-small"

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5"

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    refresh_token_expire_days: int = 7

    @property
    def database_url(self) -> URL:
        """Assemble the connection URL as an object rather than a string.

        str(URL) masks the password as '***', so anything that stringifies
        this on the way to the driver produces a URL that cannot connect.
        """
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the settings, parsed once and reused.

    The cache also defers the first read until something asks for it, so a
    missing variable fails where it can be reported rather than during an
    import.
    """
    return Settings()
