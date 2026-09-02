from typing import Any, cast

import pytest
from langfuse import Langfuse

from app.core.prompts import (
    JOB_POST_SKILLS,
    PRODUCTION,
    RESUME_SKILLS,
    TEMPLATES,
    LangfusePromptStore,
    StaticPromptStore,
    create_prompt_store,
    render_template,
)


@pytest.fixture
def prompts() -> StaticPromptStore:
    return StaticPromptStore({"greeting": "Hello {{name}}, meet {{name}}."})


def test_a_variable_is_substituted_everywhere_it_appears(
    prompts: StaticPromptStore,
) -> None:
    assert prompts.render("greeting", name="Ada") == "Hello Ada, meet Ada."


def test_whitespace_inside_the_braces_is_still_a_placeholder() -> None:
    assert render_template("read {{ content }}", {"content": "a resume"}) == (
        "read a resume"
    )


def test_a_placeholder_nobody_filled_is_an_error() -> None:
    """The model would otherwise be asked about the literal text {{content}}."""
    with pytest.raises(ValueError, match="content"):
        render_template("read {{content}}", {})


def test_a_variable_no_placeholder_uses_is_an_error(
    prompts: StaticPromptStore,
) -> None:
    """A rename that landed on one side only, seen from the other side."""
    with pytest.raises(ValueError, match="subject"):
        prompts.render("greeting", name="Ada", subject="prompts")


def test_an_unknown_prompt_is_an_error_rather_than_an_empty_instruction(
    prompts: StaticPromptStore,
) -> None:
    with pytest.raises(KeyError, match="farewell"):
        prompts.render("farewell", name="Ada")


@pytest.mark.parametrize("name", [JOB_POST_SKILLS, RESUME_SKILLS])
def test_a_shipped_prompt_carries_the_text_it_is_asked_about(name: str) -> None:
    """Guards the syntax swap: a leftover {content} renders without the text."""
    rendered = StaticPromptStore().render(name, content="ran k8s in anger")

    assert "ran k8s in anger" in rendered
    assert "{" not in rendered


class StubPrompt:
    def __init__(self, text: str) -> None:
        self.prompt = text


class StubLangfuse:
    """Enough of the client for the store: fetching and linking."""

    def __init__(self, text: str = "Served: {{content}}") -> None:
        self.text = text
        self.fetched: list[tuple[str, dict[str, Any]]] = []
        self.linked: list[Any] = []

    def get_prompt(self, name: str, **options: Any) -> StubPrompt:
        self.fetched.append((name, options))

        return StubPrompt(self.text)

    def update_current_generation(self, **fields: Any) -> None:
        self.linked.append(fields["prompt"])


def store(stub: StubLangfuse) -> LangfusePromptStore:
    return LangfusePromptStore(cast(Langfuse, stub))


def test_the_served_text_wins_over_the_one_in_the_repository() -> None:
    stub = StubLangfuse()

    assert store(stub).render(JOB_POST_SKILLS, content="a posting") == (
        "Served: a posting"
    )


def test_the_shipped_text_goes_along_as_the_fallback() -> None:
    """An unreachable server costs the wording of the commit, not the call."""
    stub = StubLangfuse()

    store(stub).render(JOB_POST_SKILLS, content="a posting")

    name, options = stub.fetched[0]
    assert name == JOB_POST_SKILLS
    assert options["fallback"] == TEMPLATES[JOB_POST_SKILLS]
    assert options["label"] == PRODUCTION


def test_a_served_text_is_filled_as_strictly_as_a_shipped_one() -> None:
    """The SDK's own compile() would leave {{gap}} in the prompt instead."""
    stub = StubLangfuse("Served: {{gap}}")

    with pytest.raises(ValueError, match="gap"):
        store(stub).render(JOB_POST_SKILLS, content="a posting")


def test_the_version_that_was_used_is_hung_on_the_generation() -> None:
    """Without the link, cost per prompt version cannot be read back."""
    stub = StubLangfuse()

    store(stub).render(JOB_POST_SKILLS, content="a posting")

    assert stub.linked[0].prompt == stub.text


def test_warming_fetches_every_shipped_prompt() -> None:
    """So no request is the one that pays for a blocking fetch."""
    stub = StubLangfuse()

    store(stub).warm()

    assert [name for name, _ in stub.fetched] == list(TEMPLATES)


def test_a_prompt_with_no_shipped_text_is_never_fetched() -> None:
    """It would have no fallback, so an outage would leave no instruction."""
    stub = StubLangfuse()

    with pytest.raises(KeyError, match="invented"):
        store(stub).render("invented", content="a posting")

    assert stub.fetched == []


def test_without_a_tracer_the_prompts_come_from_the_repository() -> None:
    """get_prompt on a keyless client raises rather than falling back."""
    assert isinstance(create_prompt_store(None), StaticPromptStore)


def test_with_a_tracer_the_prompts_come_from_langfuse() -> None:
    assert isinstance(
        create_prompt_store(cast(Langfuse, StubLangfuse())), LangfusePromptStore
    )
