import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.security import hash_password
from app.models.document import Document
from app.models.interview import InterviewSession, Message
from app.models.match import Match
from app.models.resume import Resume
from app.models.user import User
from app.schemas.dashboard import (
    ContinueInterviewStep,
    MatchStep,
    PractiseStep,
    Step,
)
from app.services.dashboard import STEPS_PER_KIND, next_steps

Factory = async_sessionmaker[AsyncSession]

QUESTIONS = 5


@dataclass(frozen=True)
class Owned:
    """A resume and the account it belongs to: what a match or interview is run by."""

    user_id: uuid.UUID
    resume_id: uuid.UUID


async def a_user(factory: Factory) -> uuid.UUID:
    async with factory() as db:
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_password(uuid.uuid4().hex),
        )
        db.add(user)
        await db.commit()

        return user.id


async def a_resume(factory: Factory, user_id: uuid.UUID) -> Owned:
    async with factory() as db:
        resume = Resume(user_id=user_id, content="Five years of Python.")
        db.add(resume)
        await db.commit()

        return Owned(user_id, resume.id)


async def a_posting(factory: Factory, title: str = "Backend developer") -> uuid.UUID:
    async with factory() as db:
        document = Document(
            title=title, content="Python and Docker.", content_hash=uuid.uuid4().hex * 2
        )
        db.add(document)
        await db.commit()

        return document.id


async def a_match(
    factory: Factory, resume: Owned, document_id: uuid.UUID, score: float = 0.5
) -> None:
    async with factory() as db:
        db.add(
            Match(
                user_id=resume.user_id,
                resume_id=resume.resume_id,
                document_id=document_id,
                document_title="Snapshot title",
                score=score,
                matched_keywords=[],
                missing_keywords=[],
                suggestions=[],
                notes=[],
                matched_evidence={},
                retrieved_chunk_ids=[],
            )
        )
        await db.commit()


async def an_interview(
    factory: Factory,
    resume: Owned,
    document_id: uuid.UUID,
    *,
    status: str = "active",
    answered: int = 0,
) -> uuid.UUID:
    """A session of QUESTIONS questions, `answered` of them answered and evaluated."""
    async with factory() as db:
        session = InterviewSession(
            user_id=resume.user_id,
            resume_id=resume.resume_id,
            document_id=document_id,
            document_title="Snapshot title",
            status=status,
            plan=[{"question": "?", "requirement": "Python"}] * QUESTIONS,
        )
        db.add(session)
        await db.flush()

        roles = ["interviewer"] + ["candidate", "evaluator", "interviewer"] * answered
        db.add_all(
            Message(session_id=session.id, position=position, role=role, content="…")
            for position, role in enumerate(roles)
        )
        await db.commit()

        return session.id


async def delete_resume(factory: Factory, resume: Owned) -> None:
    async with factory() as db:
        await db.execute(delete(Resume).where(Resume.id == resume.resume_id))
        await db.commit()


async def steps_for(factory: Factory, user_id: uuid.UUID) -> list[Step]:
    async with factory() as db:
        return await next_steps(db, user_id)


def kinds(steps: list[Step]) -> list[str]:
    return [step.kind for step in steps]


async def test_a_new_account_is_asked_for_a_resume_and_a_posting(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)

    steps = await steps_for(session_factory, user_id)

    assert kinds(steps) == ["add_resume", "add_posting"]


async def test_without_a_resume_nothing_else_is_suggested(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)
    await a_posting(session_factory)

    steps = await steps_for(session_factory, user_id)

    assert kinds(steps) == ["add_resume"]


async def test_without_postings_nothing_else_is_suggested(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)
    await a_resume(session_factory, user_id)

    steps = await steps_for(session_factory, user_id)

    assert kinds(steps) == ["add_posting"]


async def test_a_posting_without_a_match_is_offered_with_the_newest_resume(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)
    await a_resume(session_factory, user_id)
    newest = await a_resume(session_factory, user_id)
    document_id = await a_posting(session_factory, "Data engineer")

    steps = await steps_for(session_factory, user_id)

    assert steps == [
        MatchStep(
            document_id=document_id,
            document_title="Data engineer",
            resume_id=newest.resume_id,
        )
    ]


async def test_a_match_without_an_interview_is_offered_for_practice(
    session_factory: Factory,
) -> None:
    resume = await a_resume(session_factory, await a_user(session_factory))
    document_id = await a_posting(session_factory, "Data engineer")
    await a_match(session_factory, resume, document_id, score=0.72)

    steps = await steps_for(session_factory, resume.user_id)

    assert steps == [
        PractiseStep(
            document_id=document_id,
            document_title="Data engineer",
            resume_id=resume.resume_id,
            score=0.72,
        )
    ]


async def test_an_unfinished_interview_is_offered_with_its_progress(
    session_factory: Factory,
) -> None:
    resume = await a_resume(session_factory, await a_user(session_factory))
    document_id = await a_posting(session_factory, "Data engineer")
    await a_match(session_factory, resume, document_id)
    session_id = await an_interview(session_factory, resume, document_id, answered=2)

    steps = await steps_for(session_factory, resume.user_id)

    assert steps == [
        ContinueInterviewStep(
            session_id=session_id,
            document_id=document_id,
            document_title="Data engineer",
            answered=2,
            question_count=QUESTIONS,
        )
    ]


async def test_steps_come_in_order_interviews_then_matches_then_practice(
    session_factory: Factory,
) -> None:
    resume = await a_resume(session_factory, await a_user(session_factory))
    to_practise = await a_posting(session_factory, "Practise me")
    await a_match(session_factory, resume, to_practise)
    to_continue = await a_posting(session_factory, "Continue me")
    await a_match(session_factory, resume, to_continue)
    await an_interview(session_factory, resume, to_continue)
    await a_posting(session_factory, "Match me")

    steps = await steps_for(session_factory, resume.user_id)

    assert kinds(steps) == ["continue_interview", "match", "practise"]


async def test_each_kind_is_capped_and_newest_postings_come_first(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)
    await a_resume(session_factory, user_id)
    titles = [f"Posting {number}" for number in range(STEPS_PER_KIND + 1)]
    for title in titles:
        await a_posting(session_factory, title)

    steps = await steps_for(session_factory, user_id)

    newest_first = list(reversed(titles))[:STEPS_PER_KIND]
    assert [step.document_title for step in steps if isinstance(step, MatchStep)] == (
        newest_first
    )


async def test_practice_takes_the_best_match_per_posting_best_first(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)
    weaker = await a_resume(session_factory, user_id)
    stronger = await a_resume(session_factory, user_id)
    first = await a_posting(session_factory, "First")
    second = await a_posting(session_factory, "Second")
    await a_match(session_factory, weaker, first, score=0.4)
    await a_match(session_factory, stronger, first, score=0.8)
    await a_match(session_factory, weaker, second, score=0.6)

    steps = await steps_for(session_factory, user_id)

    practise = [step for step in steps if isinstance(step, PractiseStep)]
    assert [(step.document_id, step.score) for step in practise] == [
        (first, 0.8),
        (second, 0.6),
    ]
    assert practise[0].resume_id == stronger.resume_id


async def test_the_cap_on_practice_keeps_the_best_scores(
    session_factory: Factory,
) -> None:
    resume = await a_resume(session_factory, await a_user(session_factory))
    for score in [0.9, 0.1, 0.8, 0.7]:
        document_id = await a_posting(session_factory, f"Scored {score}")
        await a_match(session_factory, resume, document_id, score=score)

    steps = await steps_for(session_factory, resume.user_id)

    assert [step.score for step in steps if isinstance(step, PractiseStep)] == [
        0.9,
        0.8,
        0.7,
    ]


async def test_a_finished_interview_is_neither_continued_nor_practised_again(
    session_factory: Factory,
) -> None:
    resume = await a_resume(session_factory, await a_user(session_factory))
    document_id = await a_posting(session_factory)
    await a_match(session_factory, resume, document_id)
    await an_interview(session_factory, resume, document_id, status="finished")

    steps = await steps_for(session_factory, resume.user_id)

    assert kinds(steps) == ["add_another_posting"]


async def test_a_deleted_posting_leaves_no_step_behind(
    session_factory: Factory,
) -> None:
    resume = await a_resume(session_factory, await a_user(session_factory))
    await a_posting(session_factory, "Still here")
    gone = await a_posting(session_factory, "Gone")
    await a_match(session_factory, resume, gone)
    await an_interview(session_factory, resume, gone)
    async with session_factory() as db:
        await db.execute(delete(Document).where(Document.id == gone))
        await db.commit()

    steps = await steps_for(session_factory, resume.user_id)

    assert kinds(steps) == ["match"]


async def test_a_match_whose_resume_was_deleted_is_not_offered_for_practice(
    session_factory: Factory,
) -> None:
    user_id = await a_user(session_factory)
    await a_resume(session_factory, user_id)
    gone = await a_resume(session_factory, user_id)
    document_id = await a_posting(session_factory)
    await a_match(session_factory, gone, document_id)
    await delete_resume(session_factory, gone)

    steps = await steps_for(session_factory, user_id)

    assert kinds(steps) == ["add_another_posting"]


async def test_an_interview_whose_resume_was_deleted_is_not_offered_to_continue(
    session_factory: Factory,
) -> None:
    """Answers are judged against the resume, so that interview cannot go on."""
    user_id = await a_user(session_factory)
    await a_resume(session_factory, user_id)
    gone = await a_resume(session_factory, user_id)
    document_id = await a_posting(session_factory)
    await a_match(session_factory, gone, document_id)
    await an_interview(session_factory, gone, document_id)
    await delete_resume(session_factory, gone)

    steps = await steps_for(session_factory, user_id)

    assert kinds(steps) == ["add_another_posting"]


async def test_another_accounts_work_does_not_change_your_steps(
    session_factory: Factory,
) -> None:
    """Postings are shared; matches, interviews and resumes are not (NFR-1)."""
    owner = await a_user(session_factory)
    await a_resume(session_factory, owner)
    others = await a_resume(session_factory, await a_user(session_factory))
    document_id = await a_posting(session_factory)
    await a_match(session_factory, others, document_id)
    await an_interview(session_factory, others, document_id)

    steps = await steps_for(session_factory, owner)

    assert kinds(steps) == ["match"]


async def test_another_accounts_resume_does_not_count_as_yours(
    session_factory: Factory,
) -> None:
    owner = await a_user(session_factory)
    await a_resume(session_factory, await a_user(session_factory))
    await a_posting(session_factory)

    steps = await steps_for(session_factory, owner)

    assert kinds(steps) == ["add_resume"]
