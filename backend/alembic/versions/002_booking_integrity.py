"""002 booking integrity

Revision ID: 002
Revises: 001
Create Date: 2026-10-26

Bookings:
  - appointment_datetime / created_at / updated_at → timestamptz. Existing
    naive values were always written as UTC, so they're converted AT TIME ZONE
    'UTC' (same instant, now explicit).
  - uq_bookings_active_slot: partial unique index on (vehicle_vin,
    appointment_datetime) for pending/confirmed bookings, so two concurrent
    requests can't both take the same slot (the route's SELECT-then-INSERT
    check alone is racy).
  - fk_bookings_vehicle_vin: bookings.vehicle_vin → vehicle_inventory.vin.

Creating the index fails if active duplicates already exist, and the FK fails
if a booking points at an unknown VIN — both deliberately: those rows need a
human decision, not a silent cancel/delete.

Idempotent: every step checks the current schema first, so re-running it (or
running it against a database that was partly fixed by hand) is a no-op.
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

_TS_COLUMNS = ("appointment_datetime", "created_at", "updated_at")
_SLOT_INDEX = "uq_bookings_active_slot"
_VIN_FK = "fk_bookings_vehicle_vin"


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

    op.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_SLOT_INDEX}
            ON bookings (vehicle_vin, appointment_datetime)
            WHERE status IN ('pending', 'confirmed');
    """)

    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                            WHERE conname = '{_VIN_FK}'
                              AND conrelid = 'bookings'::regclass) THEN
                ALTER TABLE bookings ADD CONSTRAINT {_VIN_FK}
                    FOREIGN KEY (vehicle_vin) REFERENCES vehicle_inventory (vin);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(f"ALTER TABLE bookings DROP CONSTRAINT IF EXISTS {_VIN_FK};")
    op.execute(f"DROP INDEX IF EXISTS {_SLOT_INDEX};")
    for column in _TS_COLUMNS:
        _retype(column, "timestamp with time zone", "timestamp")
