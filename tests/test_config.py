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
    """Drop every variable that maps to a Settings field before each test.

    Settings reads the real environment as well as the file under test, so a
    developer with OPENAI_API_KEY exported would fail the tests that assert
    it is unset. Clearing here makes the file the only source, and keeps the
    one test that deliberately sets a variable meaningful.
    """
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


def test_misspelt_key_in_env_file_fails_at_startup(tmp_path: Path) -> None:
    """A typo has to name itself instead of surfacing as a 503 later.

    OPEN_API_KEY is the real one that cost an hour; the point is that
    Settings() raises here rather than leaving openai_api_key unset.
    """
    env_file = write_env(tmp_path, "OPEN_API_KEY=sk-typo\n")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=env_file)

    assert "open_api_key" in str(excinfo.value).lower()


def test_misspelt_key_with_no_value_is_tolerated(tmp_path: Path) -> None:
    """An empty line is a placeholder, not a typo worth failing on.

    .env.example ships keys with nothing after the '=', and pydantic drops
    them before the extra check. Documented here so the behaviour is a
    decision rather than a surprise.
    """
    settings = Settings(_env_file=write_env(tmp_path, "OPEN_API_KEY=\n"))

    assert settings.openai_api_key is None


def test_unknown_environment_variable_is_still_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check reaches the file only -- the container's env is untouched.

    Environment variables are matched to fields by name, so an unknown one
    never reaches the model and extra="forbid" cannot see it. This is why
    docker-compose mounts .env into the api container.
    """
    monkeypatch.setenv("OPEN_API_KEY", "sk-typo")

    settings = Settings(_env_file=write_env(tmp_path))

    assert settings.openai_api_key is None


def test_env_example_declares_only_known_fields() -> None:
    """Every key in the committed example must exist on the model.

    Without this, .env.example drifts into a file that fails the moment it
    is copied to .env -- which is the first thing anyone does.
    """
    assert env_example_keys() <= set(Settings.model_fields)


def test_env_example_declares_every_required_field() -> None:
    """And the other direction: nothing required may be missing from it.

    A new field without a default that never reaches the example turns that
    first copy into a startup error listing a name the newcomer has never
    seen.
    """
    required = {
        name for name, field in Settings.model_fields.items() if field.is_required()
    }

    assert required <= env_example_keys()
