"""
The mock interview (FR-4) as a LangGraph graph: one turn per request.

The graph never touches the database. It is handed the session as state, and hands back
the messages the turn produced and what changed; app.services.interview writes them.
Our tables are the only state there is, so there is no checkpointer (spec, FR-4, D-4).
"""

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.services.interviewing import (
    CRITERIA,
    AnswerEvaluator,
    CriterionVerdict,
    QuestionPlanner,
    Usage,
)
from app.services.matching import cover, evidence

DEFAULT_QUESTIONS = 5

STRONG_ANSWER = 2 / 3
"""An answer meeting two criteria of three counts as a strength in the summary."""

Phase = Literal["start", "answer", "finish"]
Role = Literal["interviewer", "candidate", "evaluator"]


class InterviewModelError(Exception):
    """The model answered in a shape the interview cannot use; nothing is saved."""


@dataclass(frozen=True)
class PostingChunk:
    """A fragment of the posting the planner is shown."""

    id: str
    content: str


@dataclass(frozen=True)
class Evaluation:
    """What one evaluated answer contributes to the summary."""

    requirement: str
    score: float
    tip: str


@dataclass(frozen=True)
class NewMessage:
    """A message the turn produced, for the service to write."""

    role: Role
    content: str
    requirement: str | None = None
    verdicts: dict[str, dict[str, Any]] | None = None
    score: float | None = None
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None


class InterviewState(TypedDict, total=False):
    """
    One turn's view of a session.

    The caller fills what it has read from the database; the nodes add the rest.
    `asked` counts questions already asked, so plan[asked] is the next one.
    """

    phase: Phase
    target_role: str | None
    resume_text: str
    resume_skills: list[str] | None
    requirements: list[str]
    posting_chunks: list[PostingChunk]
    plan: list[dict[str, str]]
    asked: int
    evaluations: Annotated[list[Evaluation], operator.add]
    pending_answer: str
    new_messages: Annotated[list[NewMessage], operator.add]
    planning: Usage
    finished: bool
    score: float | None
    summary: dict[str, Any]


def order_requirements(
    requirements: list[str], resume: str, skills: list[str] | None, limit: int
) -> list[str]:
    """Put what the resume lacks first, then what it has, and keep the first `limit`."""
    matched, missing = cover(requirements, evidence(resume, skills))

    return (missing + matched)[:limit]


def answer_score(verdicts: dict[str, CriterionVerdict]) -> float:
    """Return the share of the rubric an answer meets."""
    return round(sum(verdicts[name].met for name in CRITERIA) / len(CRITERIA), 3)


def summarize_evaluations(
    evaluations: list[Evaluation],
) -> tuple[float | None, dict[str, Any]]:
    """Put the session's score and summary together from what was already judged."""
    if not evaluations:
        return None, {"strengths": [], "improvements": []}

    score = round(sum(item.score for item in evaluations) / len(evaluations), 3)
    strengths = [
        item.requirement for item in evaluations if item.score >= STRONG_ANSWER
    ]
    improvements = [
        {"requirement": item.requirement, "tip": item.tip}
        for item in evaluations
        if item.score < STRONG_ANSWER
    ]

    return score, {"strengths": strengths, "improvements": improvements}


class _Nodes:
    """The graph's nodes, bound to the models they call."""

    def __init__(
        self, planner: QuestionPlanner, evaluator: AnswerEvaluator, limit: int
    ) -> None:
        self._planner = planner
        self._evaluator = evaluator
        self._limit = limit

    async def retrieve_questions(self, state: InterviewState) -> InterviewState:
        """Plan the questions up front: one per requirement, gaps first."""
        wanted = order_requirements(
            state["requirements"],
            state["resume_text"],
            state.get("resume_skills"),
            self._limit,
        )
        if not wanted:
            raise ValueError("A posting without requirements has nothing to ask about")

        chunks = state.get("posting_chunks", [])
        answer, usage = await self._planner.plan(
            wanted,
            "\n\n".join(chunk.content for chunk in chunks),
            state.get("target_role"),
        )

        planned = [question.requirement for question in answer.questions]
        if planned != wanted:
            raise InterviewModelError(
                "The planner did not ask one question per requirement, in order"
            )

        return {
            "plan": [question.model_dump() for question in answer.questions],
            "asked": 0,
            "planning": usage,
        }

    @staticmethod
    def ask_question(state: InterviewState) -> InterviewState:
        """Ask the next question of the plan."""
        asked = state["asked"]
        item = state["plan"][asked]
        usage = state.get("planning")
        # The question that follows planning carries what planning saw and cost.
        message = NewMessage(
            role="interviewer",
            content=item["question"],
            requirement=item["requirement"],
            retrieved_chunk_ids=(
                [chunk.id for chunk in state.get("posting_chunks", [])]
                if usage is not None
                else []
            ),
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
        )

        return {"asked": asked + 1, "new_messages": [message]}

    @staticmethod
    def collect_answer(state: InterviewState) -> InterviewState:
        """Record the candidate's answer to the question last asked."""
        asked = state["asked"]
        if asked == 0:
            raise ValueError("No question has been asked yet")

        message = NewMessage(
            role="candidate",
            content=state["pending_answer"],
            requirement=state["plan"][asked - 1]["requirement"],
        )

        return {"new_messages": [message]}

    async def evaluate_answer(self, state: InterviewState) -> InterviewState:
        """Judge the answer against the rubric; the score is counted here, not asked."""
        item = state["plan"][state["asked"] - 1]
        rubric, usage = await self._evaluator.evaluate(
            item["question"],
            item["requirement"],
            state["pending_answer"],
            state["resume_text"],
        )
        if set(rubric.verdicts) != set(CRITERIA):
            raise InterviewModelError("The evaluator did not judge every criterion")

        score = answer_score(rubric.verdicts)
        message = NewMessage(
            role="evaluator",
            content=rubric.tip,
            requirement=item["requirement"],
            verdicts={name: rubric.verdicts[name].model_dump() for name in CRITERIA},
            score=score,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        evaluation = Evaluation(
            requirement=item["requirement"], score=score, tip=rubric.tip
        )

        return {"new_messages": [message], "evaluations": [evaluation]}

    @staticmethod
    def summarize(state: InterviewState) -> InterviewState:
        """Close the session. No model: it only assembles what was already judged."""
        score, summary = summarize_evaluations(state.get("evaluations", []))

        return {"finished": True, "score": score, "summary": summary}


def _route_phase(state: InterviewState) -> str:
    return {
        "start": "retrieve_questions",
        "answer": "collect_answer",
        "finish": "summarize",
    }[state["phase"]]


def _route_after_evaluation(state: InterviewState) -> str:
    return "ask_question" if state["asked"] < len(state["plan"]) else "summarize"


def build_interview_graph(
    planner: QuestionPlanner,
    evaluator: AnswerEvaluator,
    questions: int = DEFAULT_QUESTIONS,
) -> CompiledStateGraph[InterviewState, None, InterviewState, InterviewState]:
    """Compile the graph once; each request runs one turn of it with ainvoke."""
    nodes = _Nodes(planner, evaluator, questions)
    graph = StateGraph(InterviewState)

    graph.add_node("retrieve_questions", nodes.retrieve_questions)
    graph.add_node("ask_question", nodes.ask_question)
    graph.add_node("collect_answer", nodes.collect_answer)
    graph.add_node("evaluate_answer", nodes.evaluate_answer)
    graph.add_node("summarize", nodes.summarize)

    graph.add_conditional_edges(
        START, _route_phase, ["retrieve_questions", "collect_answer", "summarize"]
    )
    graph.add_edge("retrieve_questions", "ask_question")
    graph.add_edge("ask_question", END)
    graph.add_edge("collect_answer", "evaluate_answer")
    graph.add_conditional_edges(
        "evaluate_answer", _route_after_evaluation, ["ask_question", "summarize"]
    )
    graph.add_edge("summarize", END)

    return graph.compile()
