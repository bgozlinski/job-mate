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

    The provider and Langfuse keys are optional because CI has no keys and
    must still be able to import the application and run the suite; the
    clients are what fail, and only when something actually asks them to
    work. Langfuse degrades one step further: with no keys the SDK stays
    quiet and the application behaves as if tracing were switched off.

    extra="forbid" turns a misspelt key in .env into a startup failure that
    names it. Ignoring it instead costs an hour: OPEN_API_KEY was accepted
    silently and surfaced much later as a 503 from /documents, which points
    at the provider rather than at the typo.

    Two limits are worth knowing. The check only covers the .env file --
    environment variables are matched to fields by name, so an unknown one
    is invisible to this class no matter what extra says. And a key with an
    empty value is skipped before the check, because that is what an
    unfilled line in .env.example is.
    """

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
    """claude-fable-5, claude-opus-5, claude-sonnet-5, claude-haiku-4-5.

    The ids are complete as written -- a date suffix appended to one of them
    is not a pin, it is a 404 from the provider.
    """
    llm_model: str = "claude-haiku-4-5"

    match_rate_limit: int = 20
    ingest_rate_limit: int = 60
    rate_limit_window_seconds: int = 3600
    """Per account, per hour, on the two routes that spend money (NFR-2).

    Two budgets rather than one: a match costs an LLM call on top of its
    embeddings, and sharing a counter would let an afternoon of filling the
    knowledge base lock a user out of the feature they came for.
    """

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "http://langfuse-web:3000"
    """The compose service; http://localhost:3000 only outside Docker."""

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    """How long the token handed back in the login response stays valid.

    Long, because the client that reads it -- the Streamlit dev client --
    keeps it in session state and has no way to renew it. Shortening this
    would not make that client safer, only log it out more often.
    """
    refresh_token_expire_days: int = 7
    """How long a browser session survives without the password being typed
    again. This is what the refresh token actually buys: the access cookie
    below is renewed silently for a week, and after that the user logs in."""

    cookie_access_expire_minutes: int = 15
    """The same credential as access_token_expire_minutes, over a channel
    that can renew itself, so it is short instead of long.

    Two lifetimes for one kind of token is worth justifying. A browser gets
    the token in an httpOnly cookie and can call /auth/refresh without the
    user noticing; a Bearer client cannot, and would simply stop working.
    The difference is in what the client can do, not in what the token is.

    The honest measure of what this buys: with no revocation list anywhere
    in the application, a short access token narrows the window between
    deleting an account and the deletion taking effect, and little else. It
    is not what makes the cookie safe -- httpOnly and one origin are.
    """
    cookie_secure: bool = False
    """Whether auth cookies carry the Secure flag. Must be true in
    production and false in development, and there is no value that is
    right in both: Secure over plain http means the browser silently
    discards the cookie, and no Secure over https means it travels in the
    clear."""

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
