"""Grant or revoke administrator rights on an existing account (FR-6).

Runs inside the api container, where the async driver gets the event loop it needs:

    docker compose up --build api
    docker compose exec api python -m scripts.grant_admin someone@example.com
    docker compose exec api python -m scripts.grant_admin someone@example.com --revoke

A script rather than a route: the first administrator could not be made through a route
anyway, and database access is the same boundary a manual UPDATE would cross.
"""

import argparse
import asyncio
import sys

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.models.user import User


async def set_admin(session: AsyncSession, email: str, *, admin: bool) -> bool:
    """Set the flag on the account with this address; False when there is none."""
    changed = await session.scalar(
        update(User)
        .where(User.email == email.strip().lower())
        .values(is_admin=admin)
        .returning(User.id)
    )
    await session.commit()

    return changed is not None


async def run(email: str, *, admin: bool) -> int:
    """Open a session, change the flag and report what happened."""
    engine = create_engine(get_settings())

    try:
        async with create_session_factory(engine)() as session:
            found = await set_admin(session, email, admin=admin)
    finally:
        await engine.dispose()

    if not found:
        print(f"No account with the address {email}", file=sys.stderr)

        return 1

    print(f"{email}: {'administrator' if admin else 'regular user'}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument(
        "--revoke", action="store_true", help="take the rights away instead"
    )
    args = parser.parse_args(argv)

    return asyncio.run(run(args.email, admin=not args.revoke))


if __name__ == "__main__":
    sys.exit(main())
