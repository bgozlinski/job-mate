"""
canonical city names

Rewrite the cities stored so far the way app.services.cities keeps them: one name per
city ("Warsaw" becomes "Warszawa") and no country where a city belongs ("Poland"
becomes NULL). The list is copied, not imported, so this migration means the same
thing whatever the module says later.

The downgrade does nothing: which spelling a row had is gone. The page's own spelling
is still in metadata.city.

Revision ID: 8b0c1f4e2a77
Revises: d08782adcd3e
Create Date: 2026-09-27 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b0c1f4e2a77"
down_revision: str | Sequence[str] | None = "d08782adcd3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALIASES: dict[str, str | None] = {
    "warsaw": "Warszawa",
    "cracow": "Kraków",
    "krakow": "Kraków",
    "wroclaw": "Wrocław",
    "gdansk": "Gdańsk",
    "poznan": "Poznań",
    "lodz": "Łódź",
    "bialystok": "Białystok",
    "poland": None,
    "polska": None,
}


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    for alias, name in ALIASES.items():
        bind.execute(
            sa.text("UPDATE documents SET city = :name WHERE lower(trim(city)) = :alias"),
            {"name": name, "alias": alias},
        )


def downgrade() -> None:
    """Downgrade schema: nothing to undo, see the module docstring."""
