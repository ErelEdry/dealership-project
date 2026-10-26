"""002 booking integrity

Revision ID: 002
Revises: 001
Create Date: 2026-10-26

Bookings:
  - appointment_datetime / created_at / updated_at → timestamptz. Existing
    naive values were always written as UTC, so they're converted AT TIME ZONE
    'UTC' (same instant, now explicit).

Idempotent: every step checks the current schema first, so re-running it (or
running it against a database that was partly fixed by hand) is a no-op.
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

_TS_COLUMNS = ("appointment_datetime", "created_at", "updated_at")


def _retype(column: str, from_type: str, to_type: str) -> None:
    """ALTER bookings.<column> from one timestamp flavour to the other, if needed.

    `x AT TIME ZONE 'UTC'` converts both ways: timestamp → timestamptz reads the
    naive value as UTC, and timestamptz → timestamp yields the UTC wall time.
    """
    op.execute(f"""
        DO $$
        BEGIN
            IF (SELECT data_type FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'bookings' AND column_name = '{column}')
               = '{from_type}' THEN
                ALTER TABLE bookings ALTER COLUMN {column}
                    TYPE {to_type} USING {column} AT TIME ZONE 'UTC';
            END IF;
        END $$;
    """)


def upgrade() -> None:
    for column in _TS_COLUMNS:
        _retype(column, "timestamp without time zone", "timestamptz")


def downgrade() -> None:
    for column in _TS_COLUMNS:
        _retype(column, "timestamp with time zone", "timestamp")
