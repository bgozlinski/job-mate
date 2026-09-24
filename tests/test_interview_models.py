import uuid

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.auth.security import hash_password
from app.models.document import Document
from app.models.interview import InterviewSession, Message
from app.models.resume import Resume
from app.models.user import User

PLAN = [{"question": "Tell me about Docker", "requirement": "Docker"}]


async def a_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> InterviewSession:
    """An interview with its owner, resume and posting, all written to the database."""
    async with session_factory() as db:
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_password(uuid.uuid4().hex),
        )
        db.add(user)
        await db.flush()
        resume = Resume(user_id=user.id, content="Python, Docker")
        document = Document(
            title="Backend developer",
            content="Docker",
            content_hash=uuid.uuid4().hex * 2,
        )
        db.add_all([resume, document])
        await db.flush()
        interview = InterviewSession(
            user_id=user.id,
            resume_id=resume.id,
            document_id=document.id,
            document_title=document.title,
            plan=PLAN,
        )
        db.add(interview)
        await db.commit()

    return interview


def a_message(
    interview: InterviewSession, position: int, role: str = "interviewer"
) -> Message:
    return Message(
        session_id=interview.id,
        position=position,
        role=role,
        content="Tell me about Docker",
        requirement="Docker",
    )


async def test_a_new_session_is_active(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)

    async with session_factory() as db:
        stored = await db.get(InterviewSession, interview.id)

    assert stored is not None
    assert stored.status == "active"
    assert stored.plan == PLAN


async def test_a_session_outlives_its_resume_and_posting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)

    async with session_factory() as db:
        await db.execute(delete(Resume).where(Resume.id == interview.resume_id))
        await db.execute(delete(Document).where(Document.id == interview.document_id))
        await db.commit()

    async with session_factory() as db:
        stored = await db.get(InterviewSession, interview.id)

    assert stored is not None
    assert stored.resume_id is None
    assert stored.document_id is None
    assert stored.document_title == "Backend developer"


async def test_deleting_a_session_deletes_its_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)
    async with session_factory() as db:
        db.add_all([a_message(interview, 0), a_message(interview, 1, "candidate")])
        await db.commit()

    async with session_factory() as db:
        await db.execute(
            delete(InterviewSession).where(InterviewSession.id == interview.id)
        )
        await db.commit()

    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(Message)) == 0


async def test_deleting_the_owner_deletes_their_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)

    async with session_factory() as db:
        await db.execute(delete(User).where(User.id == interview.user_id))
        await db.commit()

    async with session_factory() as db:
        assert await db.get(InterviewSession, interview.id) is None


async def test_two_messages_cannot_share_a_position(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)
    async with session_factory() as db:
        db.add(a_message(interview, 0))
        await db.commit()

    async with session_factory() as db:
        db.add(a_message(interview, 0, "candidate"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_messages_load_in_position_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)
    async with session_factory() as db:
        db.add_all([a_message(interview, 1, "candidate"), a_message(interview, 0)])
        await db.commit()

    async with session_factory() as db:
        stored = await db.get(
            InterviewSession,
            interview.id,
            options=[selectinload(InterviewSession.messages)],
        )

    assert stored is not None
    assert [message.position for message in stored.messages] == [0, 1]


async def test_retrieved_chunk_ids_default_to_an_empty_list_in_the_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)

    async with session_factory() as db:
        # Raw SQL: an ORM or Core insert would fill the column from the Python default.
        message_id = await db.scalar(
            text(
                "INSERT INTO messages (id, session_id, position, role, content) "
                "VALUES (:id, :session_id, 0, 'interviewer', '?') RETURNING id"
            ),
            {"id": uuid.uuid7(), "session_id": interview.id},
        )
        await db.commit()

    async with session_factory() as db:
        stored = await db.get(Message, message_id)

    assert stored is not None
    assert stored.retrieved_chunk_ids == []


async def test_an_unknown_role_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)

    async with session_factory() as db:
        db.add(a_message(interview, 0, "narrator"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_an_unknown_status_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    interview = await a_session(session_factory)

    async with session_factory() as db:
        stored = await db.get(InterviewSession, interview.id)
        assert stored is not None
        stored.status = "paused"
        with pytest.raises(IntegrityError):
            await db.commit()
