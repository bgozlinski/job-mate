"""Settings parsing: what .env is allowed to contain."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ENV = """\
POSTGRES_DB=jobmate
POSTGRES_USER=jobmate
POSTGRES_PASSWORD=jobmate
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=test-only-throwaway-key-padded-to-32-bytes
"""


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every variable that maps to a Settings field before each test."""
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


def env_example_keys() -> set[str]:
    """The keys declared in the committed example, as field names."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    return {
        line.split("=", 1)[0].strip().lower()
        for line in example.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def write_env(tmp_path: Path, extra: str = "") -> Path:
    """Write a complete .env into tmp_path, plus whatever extra lines say."""
    env_file = tmp_path / ".env"
    env_file.write_text(REQUIRED_ENV + extra, encoding="utf-8")
    return env_file


def test_complete_env_file_parses(tmp_path: Path) -> None:
    """The baseline the other tests vary: this file has to be valid."""
    settings = Settings(_env_file=write_env(tmp_path))

    assert settings.postgres_db == "jobmate"
    assert settings.openai_api_key is None


def test_the_cookie_settings_have_development_defaults(tmp_path: Path) -> None:
    """A .env that says nothing about cookies must still start locally."""
    settings = Settings(_env_file=write_env(tmp_path))

    assert settings.cookie_secure is False
    assert settings.cookie_access_expire_minutes < settings.access_token_expire_minutes


def test_the_cookie_settings_are_read_from_the_file(tmp_path: Path) -> None:
    minutes = 5
    env_file = write_env(
        tmp_path, f"COOKIE_SECURE=true\nCOOKIE_ACCESS_EXPIRE_MINUTES={minutes}\n"
    )

    settings = Settings(_env_file=env_file)

    assert settings.cookie_secure is True
    assert settings.cookie_access_expire_minutes == minutes


def test_misspelt_key_in_env_file_fails_at_startup(tmp_path: Path) -> None:
    """A typo has to name itself instead of surfacing as a 503 later."""
    env_file = write_env(tmp_path, "OPEN_API_KEY=sk-typo\n")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=env_file)

    assert "open_api_key" in str(excinfo.value).lower()


def test_misspelt_key_with_no_value_is_tolerated(tmp_path: Path) -> None:
    """An empty line is a placeholder, not a typo worth failing on."""
    settings = Settings(_env_file=write_env(tmp_path, "OPEN_API_KEY=\n"))

    assert settings.openai_api_key is None


def test_unknown_environment_variable_is_still_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check reaches the file only -- the container's env is untouched."""
    monkeypatch.setenv("OPEN_API_KEY", "sk-typo")

    settings = Settings(_env_file=write_env(tmp_path))

    assert settings.openai_api_key is None


def test_env_example_declares_only_known_fields() -> None:
    """Every key in the committed example must exist on the model."""
    assert env_example_keys() <= set(Settings.model_fields)


def test_env_example_declares_every_required_field() -> None:
    """And the other direction: nothing required may be missing from it."""
    required = {
        name for name, field in Settings.model_fields.items() if field.is_required()
    }

    assert required <= env_example_keys()
