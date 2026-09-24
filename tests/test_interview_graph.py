from typing import Any

import pytest

from app.services.interview_graph import (
    Evaluation,
    InterviewModelError,
    InterviewState,
    PostingChunk,
    answer_score,
    build_interview_graph,
    order_requirements,
    summarize_evaluations,
)
from app.services.interviewing import (
    CRITERIA,
    CriterionVerdict,
    PlannedQuestion,
    QuestionPlan,
    Rubric,
    Usage,
)

RESUME = "Five years of Python and PostgreSQL."
REQUIREMENTS = ["Python", "Docker", "PostgreSQL", "Kubernetes"]
CHUNKS = [
    PostingChunk(id="c1", content="We ship Python."),
    PostingChunk("c2", "On K8s."),
]


class FakePlanner:
    """Asks "About X?" for every requirement it is given, or what it is told to."""

    def __init__(self, questions: list[PlannedQuestion] | None = None) -> None:
        self.questions = questions
        self.calls: list[dict[str, Any]] = []

    async def plan(
        self, requirements: list[str], posting: str, target_role: str | None
    ) -> tuple[QuestionPlan, Usage]:
        self.calls.append(
            {"requirements": requirements, "posting": posting, "role": target_role}
        )
        questions = self.questions or [
            PlannedQuestion(question=f"About {term}?", requirement=term)
            for term in requirements
        ]

        return QuestionPlan(questions=questions), Usage(
            input_tokens=100, output_tokens=20
        )


class FakeEvaluator:
    """Meets the criteria it is told to, and nothing else."""

    def __init__(
        self, met: tuple[str, ...] = CRITERIA, tip: str = "Be specific"
    ) -> None:
        self.met = met
        self.tip = tip
        self.calls: list[tuple[str, str, str, str]] = []

    async def evaluate(
        self, question: str, requirement: str, answer: str, resume: str
    ) -> tuple[Rubric, Usage]:
        self.calls.append((question, requirement, answer, resume))
        verdicts = {
            name: CriterionVerdict(met=name in self.met, reason="because")
            for name in CRITERIA
        }

        return Rubric(verdicts=verdicts, tip=self.tip), Usage(50, 10)


def started(**overrides: Any) -> InterviewState:
    state: InterviewState = {
        "phase": "start",
        "target_role": "Backend developer",
        "resume_text": RESUME,
        "resume_skills": None,
        "requirements": REQUIREMENTS,
        "posting_chunks": CHUNKS,
    }
    state.update(overrides)  # type: ignore[typeddict-item]

    return state


def in_progress(asked: int, plan_size: int = 2, **overrides: Any) -> InterviewState:
    plan = [
        {"question": f"About {term}?", "requirement": term}
        for term in REQUIREMENTS[:plan_size]
    ]
    state: InterviewState = {
        "phase": "answer",
        "resume_text": RESUME,
        "plan": plan,
        "asked": asked,
        "evaluations": [],
        "pending_answer": "I built a Docker image for our API.",
    }
    state.update(overrides)  # type: ignore[typeddict-item]

    return state


def test_gaps_come_first_and_the_plan_is_cut_to_the_limit() -> None:
    ordered = order_requirements(REQUIREMENTS, RESUME, None, limit=3)

    assert ordered == ["Docker", "Kubernetes", "Python"]


def test_a_short_posting_gives_a_short_plan() -> None:
    assert order_requirements(["Python"], RESUME, None, limit=5) == ["Python"]


def test_skills_count_as_evidence() -> None:
    ordered = order_requirements(["Docker", "Go"], "", ["Docker"], limit=5)

    assert ordered == ["Go", "Docker"]


def test_an_answer_scores_the_share_of_criteria_met() -> None:
    verdicts = {name: CriterionVerdict(met=name == "on_topic") for name in CRITERIA}

    assert answer_score(verdicts) == pytest.approx(1 / 3, abs=0.001)


def test_summary_splits_strengths_from_improvements() -> None:
    evaluations = [
        Evaluation(requirement="Docker", score=1.0, tip="-"),
        Evaluation(requirement="Kubernetes", score=0.333, tip="Name a cluster you ran"),
    ]

    score, summary = summarize_evaluations(evaluations)

    assert score == pytest.approx(0.666, abs=0.001)
    assert summary == {
        "strengths": ["Docker"],
        "improvements": [
            {"requirement": "Kubernetes", "tip": "Name a cluster you ran"}
        ],
    }


def test_summary_of_nothing_has_no_score() -> None:
    assert summarize_evaluations([]) == (None, {"strengths": [], "improvements": []})


async def test_start_plans_and_asks_the_first_question() -> None:
    planner = FakePlanner()
    graph = build_interview_graph(planner, FakeEvaluator(), questions=3)

    result = await graph.ainvoke(started())

    assert planner.calls[0]["requirements"] == ["Docker", "Kubernetes", "Python"]
    assert planner.calls[0]["posting"] == "We ship Python.\n\nOn K8s."
    assert [item["requirement"] for item in result["plan"]] == [
        "Docker",
        "Kubernetes",
        "Python",
    ]
    assert result["asked"] == 1
    [message] = result["new_messages"]
    assert message.role == "interviewer"
    assert message.content == "About Docker?"
    assert message.requirement == "Docker"
    assert message.retrieved_chunk_ids == ["c1", "c2"]
    assert (message.input_tokens, message.output_tokens) == (100, 20)
    assert not result.get("finished")


async def test_start_without_requirements_is_refused() -> None:
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())

    with pytest.raises(ValueError, match="requirements"):
        await graph.ainvoke(started(requirements=[]))


async def test_a_planner_that_skips_a_requirement_is_an_error() -> None:
    planner = FakePlanner([PlannedQuestion(question="?", requirement="Docker")])
    graph = build_interview_graph(planner, FakeEvaluator(), questions=2)

    with pytest.raises(InterviewModelError):
        await graph.ainvoke(started())


async def test_an_answer_is_judged_and_the_next_question_asked() -> None:
    evaluator = FakeEvaluator(met=("on_topic", "concrete_example"))
    graph = build_interview_graph(FakePlanner(), evaluator)

    result = await graph.ainvoke(in_progress(asked=1))

    roles = [message.role for message in result["new_messages"]]
    assert roles == ["candidate", "evaluator", "interviewer"]
    answer, evaluation, question = result["new_messages"]
    assert answer.content == "I built a Docker image for our API."
    assert answer.requirement == "Python"
    assert evaluator.calls[0][1] == "Python"
    assert evaluation.score == pytest.approx(0.667, abs=0.001)
    assert evaluation.content == "Be specific"
    assert evaluation.verdicts is not None
    assert set(evaluation.verdicts) == set(CRITERIA)
    assert (evaluation.input_tokens, evaluation.output_tokens) == (50, 10)
    assert question.content == "About Docker?"
    assert question.retrieved_chunk_ids == []
    assert question.input_tokens is None
    assert result["asked"] == len(result["plan"])
    assert not result.get("finished")


async def test_the_last_answer_ends_the_session_with_a_summary() -> None:
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    earlier = [Evaluation(requirement="Python", score=0.0, tip="Give an example")]

    result = await graph.ainvoke(in_progress(asked=2, evaluations=earlier))

    roles = [message.role for message in result["new_messages"]]
    assert roles == ["candidate", "evaluator"]
    assert result["finished"] is True
    assert result["score"] == pytest.approx(0.5)
    assert result["summary"] == {
        "strengths": ["Docker"],
        "improvements": [{"requirement": "Python", "tip": "Give an example"}],
    }


async def test_an_evaluator_that_skips_a_criterion_is_an_error() -> None:
    class Partial(FakeEvaluator):
        async def evaluate(
            self, question: str, requirement: str, answer: str, resume: str
        ) -> tuple[Rubric, Usage]:
            return Rubric(verdicts={"on_topic": CriterionVerdict(met=True)}), Usage()

    graph = build_interview_graph(FakePlanner(), Partial())

    with pytest.raises(InterviewModelError):
        await graph.ainvoke(in_progress(asked=1))


async def test_an_answer_before_any_question_is_refused() -> None:
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())

    with pytest.raises(ValueError, match="No question"):
        await graph.ainvoke(in_progress(asked=0))


async def test_finishing_early_summarizes_without_calling_a_model() -> None:
    planner, evaluator = FakePlanner(), FakeEvaluator()
    graph = build_interview_graph(planner, evaluator)
    earlier = [Evaluation(requirement="Python", score=1.0, tip="-")]

    result = await graph.ainvoke(
        in_progress(asked=1, phase="finish", evaluations=earlier)
    )

    assert result.get("new_messages", []) == []
    assert result["finished"] is True
    assert result["score"] == 1.0
    assert planner.calls == []
    assert evaluator.calls == []
