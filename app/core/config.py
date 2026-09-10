"""Settings read from the environment."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Every value the application reads from its environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
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
    """claude-fable-5, claude-opus-5, claude-sonnet-5, claude-haiku-4-5."""
    llm_model: str = "claude-haiku-4-5"

    match_rate_limit: int = 20
    ingest_rate_limit: int = 60
    rate_limit_window_seconds: int = 3600
    """Per account, per hour, on the two routes that spend money (NFR-2)."""

    scraper_allowed_hosts: list[str] = ["justjoin.it"]
    """The only hosts a posting may be read from (NFR-5, NFR-1)."""
    scraper_timeout_seconds: float = 10.0
    scraper_max_bytes: int = 2 * 1024 * 1024
    scraper_max_redirects: int = 3
    """
    What one fetch may cost. The pages seen so far weigh about a megabyte, so the cap is
    a factor of two rather than of a hundred -- it exists to bound what a hostile or
    broken response can spend, and a limit far above anything real does not do that.
    """

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "http://langfuse-web:3000"
    """The compose service; http://localhost:3000 only outside Docker."""

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    """How long the token handed back in the login response stays valid."""
    refresh_token_expire_days: int = 7
    """
    How long a browser session survives without the password being typed again. This is
    what the refresh token actually buys: the access cookie below is renewed silently
    for a week, and after that the user logs in.
    """

    cookie_access_expire_minutes: int = 15
    """
    The same credential as access_token_expire_minutes, over a channel that can renew
    itself, so it is short instead of long.
    """
    cookie_path_prefix: str = ""
    """The path prefix the browser reaches this API under, if any."""
    cookie_secure: bool = False
    """
    Whether auth cookies carry the Secure flag. Must be true in production and false in
    development, and there is no value that is right in both: Secure over plain http
    means the browser silently discards the cookie, and no Secure over https means it
    travels in the clear.
    """

    @property
    def database_url(self) -> URL:
        """Assemble the connection URL as an object rather than a string."""
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
    """Return the settings, parsed once and reused."""
    return Settings()
