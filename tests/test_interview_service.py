import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import hash_password
from app.models.chunk import EMBEDDING_DIMENSIONS, Chunk
from app.models.document import Document
from app.models.interview import InterviewSession, Message
from app.models.resume import Resume
from app.models.user import User
from app.services import interview
from app.services.interview_graph import InterviewModelError, build_interview_graph
from app.services.interviewing import CRITERIA, Rubric, Usage
from tests.test_interview_graph import FakeEvaluator, FakePlanner

Factory = async_sessionmaker[AsyncSession]

REQUIREMENTS = ["Python", "Docker"]
RESUME = "Five years of Python."


class SlowEvaluator(FakeEvaluator):
    """Takes long enough for a second request to queue behind the first."""

    async def evaluate(
        self, question: str, requirement: str, answer: str, resume: str
    ) -> tuple[Rubric, Usage]:
        await asyncio.sleep(0.3)

        return await super().evaluate(question, requirement, answer, resume)


class BrokenEvaluator(FakeEvaluator):
    async def evaluate(
        self, question: str, requirement: str, answer: str, resume: str
    ) -> tuple[Rubric, Usage]:
        raise InterviewModelError("unusable answer")


async def owner_resume_and_posting(
    session_factory: Factory, requirements: list[str] | None = REQUIREMENTS
) -> tuple[uuid.UUID, Resume, Document]:
    async with session_factory() as db:
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_password(uuid.uuid4().hex),
        )
        db.add(user)
        await db.flush()
        resume = Resume(
            user_id=user.id, content=RESUME, target_role="Backend developer"
        )
        document = Document(
            title="Backend developer",
            content="Python and Docker.",
            content_hash=uuid.uuid4().hex * 2,
            requirements=requirements,
        )
        db.add_all([resume, document])
        await db.flush()
        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=0,
                content="Python and Docker.",
                embedding=[0.0] * EMBEDDING_DIMENSIONS,
            )
        )
        await db.commit()

        return user.id, resume, document


async def started(
    session_factory: Factory, evaluator: FakeEvaluator | None = None
) -> tuple[uuid.UUID, InterviewSession]:
    user_id, resume, document = await owner_resume_and_posting(session_factory)
    graph = build_interview_graph(FakePlanner(), evaluator or FakeEvaluator())

    async with session_factory() as db:
        session = await interview.start_session(db, graph, user_id, resume, document)

    return user_id, session


async def message_count(session_factory: Factory) -> int:
    async with session_factory() as db:
        return await db.scalar(select(func.count()).select_from(Message)) or 0


async def test_starting_plans_and_asks_the_first_question(
    session_factory: Factory,
) -> None:
    _, session = await started(session_factory)

    assert session.status == "active"
    assert session.document_title == "Backend developer"
    assert [item["requirement"] for item in session.plan] == ["Docker", "Python"]
    [question] = session.messages
    assert (question.position, question.role) == (0, "interviewer")
    assert question.requirement == "Docker"
    assert len(question.retrieved_chunk_ids) == 1
    assert question.input_tokens is not None


async def test_a_posting_without_requirements_cannot_be_interviewed_on(
    session_factory: Factory,
) -> None:
    user_id, resume, document = await owner_resume_and_posting(
        session_factory, requirements=None
    )
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())

    async with session_factory() as db:
        with pytest.raises(interview.NoRequirementsError):
            await interview.start_session(db, graph, user_id, resume, document)

    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(InterviewSession)) == 0


async def test_an_answer_is_judged_and_the_next_question_asked(
    session_factory: Factory,
) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())

    async with session_factory() as db:
        updated = await interview.answer(
            db, graph, user_id, session.id, session.messages[0].id, "I ran Docker."
        )

    assert [(m.position, m.role) for m in updated.messages] == [
        (0, "interviewer"),
        (1, "candidate"),
        (2, "evaluator"),
        (3, "interviewer"),
    ]
    evaluation = updated.messages[2]
    assert evaluation.score == 1.0
    assert evaluation.verdicts is not None
    assert set(evaluation.verdicts) == set(CRITERIA)
    assert updated.status == "active"


async def test_the_last_answer_closes_the_session(session_factory: Factory) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())

    async with session_factory() as db:
        first = await interview.answer(
            db, graph, user_id, session.id, session.messages[0].id, "One."
        )
    async with session_factory() as db:
        last = await interview.answer(
            db, graph, user_id, session.id, first.messages[-1].id, "Two."
        )

    assert last.status == "finished"
    assert last.score == 1.0
    assert last.summary == {"strengths": ["Docker", "Python"], "improvements": []}
    assert last.finished_at is not None
    assert [m.role for m in last.messages] == [
        "interviewer",
        "candidate",
        "evaluator",
    ] * 2


async def test_an_answer_to_an_answered_question_is_stale(
    session_factory: Factory,
) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    question_id = session.messages[0].id

    async with session_factory() as db:
        await interview.answer(db, graph, user_id, session.id, question_id, "One.")
    async with session_factory() as db:
        with pytest.raises(interview.StaleQuestionError):
            await interview.answer(db, graph, user_id, session.id, question_id, "One.")


async def test_two_copies_of_one_answer_are_judged_once(
    session_factory: Factory,
) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), SlowEvaluator())
    question_id = session.messages[0].id

    async def send() -> InterviewSession:
        async with session_factory() as db:
            return await interview.answer(
                db, graph, user_id, session.id, question_id, "I ran Docker."
            )

    results = await asyncio.gather(send(), send(), return_exceptions=True)

    assert sum(isinstance(r, InterviewSession) for r in results) == 1
    assert sum(isinstance(r, interview.StaleQuestionError) for r in results) == 1
    async with session_factory() as db:
        evaluations = await db.scalar(
            select(func.count()).select_from(Message).where(Message.role == "evaluator")
        )
    assert evaluations == 1


async def test_a_failed_model_call_saves_nothing(session_factory: Factory) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), BrokenEvaluator())
    before = await message_count(session_factory)

    async with session_factory() as db:
        with pytest.raises(InterviewModelError):
            await interview.answer(
                db, graph, user_id, session.id, session.messages[0].id, "One."
            )

    assert await message_count(session_factory) == before


async def test_someone_elses_session_is_not_found(session_factory: Factory) -> None:
    _, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    stranger = uuid.uuid4()

    async with session_factory() as db:
        with pytest.raises(interview.SessionNotFoundError):
            await interview.get_session(db, stranger, session.id)
        with pytest.raises(interview.SessionNotFoundError):
            await interview.answer(
                db, graph, stranger, session.id, session.messages[0].id, "Mine now."
            )
        with pytest.raises(interview.SessionNotFoundError):
            await interview.finish(db, graph, stranger, session.id)


async def test_finishing_early_sums_up_without_new_messages(
    session_factory: Factory,
) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())

    async with session_factory() as db:
        finished = await interview.finish(db, graph, user_id, session.id)

    assert finished.status == "finished"
    assert finished.score is None
    assert finished.summary == {"strengths": [], "improvements": []}
    assert len(finished.messages) == 1


async def test_a_finished_session_takes_no_answer_and_no_second_finish(
    session_factory: Factory,
) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    async with session_factory() as db:
        await interview.finish(db, graph, user_id, session.id)

    async with session_factory() as db:
        with pytest.raises(interview.SessionFinishedError):
            await interview.answer(
                db, graph, user_id, session.id, session.messages[0].id, "Late."
            )
    async with session_factory() as db:
        with pytest.raises(interview.SessionFinishedError):
            await interview.finish(db, graph, user_id, session.id)


async def test_without_its_resume_a_session_can_only_be_finished(
    session_factory: Factory,
) -> None:
    user_id, session = await started(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    async with session_factory() as db:
        await db.execute(delete(Resume).where(Resume.id == session.resume_id))
        await db.commit()

    async with session_factory() as db:
        with pytest.raises(interview.ResumeDeletedError):
            await interview.answer(
                db, graph, user_id, session.id, session.messages[0].id, "One."
            )
    async with session_factory() as db:
        finished = await interview.finish(db, graph, user_id, session.id)

    assert finished.status == "finished"


async def test_the_list_holds_only_the_callers_sessions_newest_first(
    session_factory: Factory,
) -> None:
    user_id, resume, document = await owner_resume_and_posting(session_factory)
    graph = build_interview_graph(FakePlanner(), FakeEvaluator())
    async with session_factory() as db:
        older = await interview.start_session(db, graph, user_id, resume, document)
    async with session_factory() as db:
        newer = await interview.start_session(db, graph, user_id, resume, document)
    await started(session_factory)

    async with session_factory() as db:
        sessions = await interview.list_sessions(db, user_id)

    assert [item.id for item in sessions] == [newer.id, older.id]
