from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.core.config import get_settings
from app.core.prompts import StaticPromptStore
from app.services import interviewing
from app.services.interviewing import (
    CRITERIA,
    CRITERION_DESCRIPTIONS,
    AnthropicAnswerEvaluator,
    AnthropicQuestionPlanner,
    CriterionAnswer,
    PlannedQuestion,
    QuestionPlan,
    RubricAnswer,
    Usage,
    describe_criteria,
    to_rubric,
)


class StubMessages:
    """Answers `parse` with a fixed object and keeps what it was asked."""

    def __init__(self, parsed: BaseModel | None) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **request: Any) -> SimpleNamespace:
        self.calls.append(request)

        return SimpleNamespace(
            parsed_output=self.parsed,
            usage=SimpleNamespace(input_tokens=321, output_tokens=45),
        )


class StubLangfuse:
    def __init__(self) -> None:
        self.generations: list[dict[str, Any]] = []

    def update_current_generation(self, **fields: Any) -> None:
        self.generations.append(fields)


@pytest.fixture
def langfuse(monkeypatch: pytest.MonkeyPatch) -> StubLangfuse:
    stub = StubLangfuse()
    monkeypatch.setattr(interviewing, "get_client", lambda: stub)

    return stub


def with_stub[T: interviewing.AnthropicQuestionPlanner | AnthropicAnswerEvaluator](
    cls: type[T], parsed: BaseModel | None
) -> tuple[T, StubMessages]:
    settings = get_settings().model_copy(
        update={"anthropic_api_key": SecretStr("test-key")}
    )
    caller = cls(settings, StaticPromptStore())
    messages = StubMessages(parsed)
    caller._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]

    return caller, messages


def prompt_of(messages: StubMessages) -> str:
    return str(messages.calls[0]["messages"][0]["content"])


def test_every_criterion_is_described() -> None:
    assert set(CRITERION_DESCRIPTIONS) == set(CRITERIA)


def test_the_criteria_are_listed_in_the_order_the_code_defines() -> None:
    names = [
        line.split(":")[0].removeprefix("- ")
        for line in describe_criteria().splitlines()
    ]

    assert names == list(CRITERIA)


def test_verdicts_are_keyed_by_criterion() -> None:
    answer = RubricAnswer(
        verdicts=[
            CriterionAnswer(criterion="on_topic", met=True, reason="It is"),
            CriterionAnswer(criterion="concrete_example", met=False),
        ],
        tip="Name the project",
    )

    rubric = to_rubric(answer)

    assert rubric.verdicts["on_topic"].met is True
    assert rubric.verdicts["on_topic"].reason == "It is"
    assert rubric.verdicts["concrete_example"].met is False
    assert rubric.tip == "Name the project"


def test_a_criterion_judged_twice_leaves_nothing_to_score() -> None:
    answer = RubricAnswer(
        verdicts=[
            CriterionAnswer(criterion="on_topic", met=True),
            CriterionAnswer(criterion="on_topic", met=False),
        ]
    )

    assert to_rubric(answer).verdicts == {}


async def test_the_planner_sends_the_requirements_and_posting(
    langfuse: StubLangfuse,
) -> None:
    plan = QuestionPlan(
        questions=[
            PlannedQuestion(question="How did you use Docker?", requirement="Docker")
        ]
    )
    planner, messages = with_stub(AnthropicQuestionPlanner, plan)

    answer, usage = await planner.plan(["Docker", "Go"], "We ship containers.", None)

    assert answer == plan
    assert usage == Usage(input_tokens=321, output_tokens=45)
    prompt = prompt_of(messages)
    assert "- Docker\n- Go" in prompt
    assert "We ship containers." in prompt
    assert "not stated" in prompt
    assert "{{" not in prompt
    assert messages.calls[0]["output_format"] is QuestionPlan
    assert langfuse.generations[0]["usage_details"] == {"input": 321, "output": 45}


async def test_a_planner_answer_that_failed_to_parse_is_an_empty_plan(
    langfuse: StubLangfuse,
) -> None:
    planner, _ = with_stub(AnthropicQuestionPlanner, None)

    answer, _ = await planner.plan(["Docker"], "", "Backend developer")

    assert answer.questions == []


async def test_the_evaluator_sends_the_rubric_and_the_answer(
    langfuse: StubLangfuse,
) -> None:
    parsed = RubricAnswer(
        verdicts=[CriterionAnswer(criterion=name, met=True) for name in CRITERIA],
        tip="Add a number",
    )
    evaluator, messages = with_stub(AnthropicAnswerEvaluator, parsed)

    rubric, usage = await evaluator.evaluate(
        "How did you use Docker?",
        "Docker",
        "I containerised our API.",
        "Python, Docker",
    )

    assert set(rubric.verdicts) == set(CRITERIA)
    assert rubric.tip == "Add a number"
    assert usage == Usage(input_tokens=321, output_tokens=45)
    prompt = prompt_of(messages)
    for name in CRITERIA:
        assert f"- {name}: " in prompt
    assert "I containerised our API." in prompt
    assert "Python, Docker" in prompt
    assert "{{" not in prompt
    assert messages.calls[0]["output_format"] is RubricAnswer


async def test_an_evaluator_answer_that_failed_to_parse_has_no_verdicts(
    langfuse: StubLangfuse,
) -> None:
    evaluator, _ = with_stub(AnthropicAnswerEvaluator, None)

    rubric, _ = await evaluator.evaluate("?", "Docker", "...", "")

    assert rubric.verdicts == {}


def test_without_a_key_the_planner_refuses_to_start() -> None:
    settings = get_settings().model_copy(update={"anthropic_api_key": None})

    with pytest.raises(RuntimeError, match="anthropic_api_key"):
        AnthropicQuestionPlanner(settings, StaticPromptStore())
