"""001 initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-27

Creates:
  - vehicle_inventory
  - validation_errors
  - bookings
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── vehicle_inventory ──────────────────────────────────────
    op.create_table(
        "vehicle_inventory",
        sa.Column("vin",          sa.String(17),  primary_key=True),
        sa.Column("dealer_id",    sa.String(50),  nullable=False),
        sa.Column("stock_id",     sa.String(50),  nullable=True),

        sa.Column("make",         sa.String(50),  nullable=False),
        sa.Column("model",        sa.String(100), nullable=False),
        sa.Column("year",         sa.Integer,     nullable=False),
        sa.Column("trim",         sa.String(100), nullable=True),
        sa.Column("body_type",    sa.String(30),  nullable=True),
        sa.Column("fuel_type",    sa.String(30),  nullable=True),
        sa.Column("transmission", sa.String(30),  nullable=True),
        sa.Column("engine",       sa.String(100), nullable=True),
        sa.Column("seats",        sa.Integer,     nullable=True),
        sa.Column("doors",        sa.Integer,     nullable=True),

        sa.Column("mileage",      sa.Integer,     nullable=False),
        sa.Column("price",        sa.Float,       nullable=False),
        sa.Column("condition",        sa.String(20), nullable=True),
        sa.Column("acquisition_cost", sa.Float,     nullable=True),
        sa.Column("colour_ext",       sa.String(50), nullable=True),
        sa.Column("colour_int",       sa.String(50), nullable=True),

        sa.Column("features",     JSON,           nullable=True),
        sa.Column("images",       JSON,           nullable=True),

        sa.Column("stock_status", sa.String(20),  nullable=False,
                  server_default="available"),

        sa.Column("arrived_date", sa.String(20),  nullable=True),

        # AI enrichment
        sa.Column("ai_lifestyle_tags",    JSON,            nullable=True),
        sa.Column("ai_segment",           sa.String(100),  nullable=True),
        sa.Column("ai_summary",           sa.Text,         nullable=True),
        sa.Column("ai_selling_points",    JSON,            nullable=True),
        sa.Column("ai_comparable_models", JSON,            nullable=True),
        sa.Column("ai_confidence",        sa.Float,        nullable=True),

        # Vector metadata
        sa.Column("content_hash",    sa.String(32),  nullable=True),
        sa.Column("embedding_doc",   sa.Text,        nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("vector_id",       sa.String(100), nullable=True),

        # Pipeline state
        sa.Column("needs_review", sa.Boolean,      nullable=False,
                  server_default="false"),
        sa.Column("enriched_at",  sa.DateTime,     nullable=True),
        sa.Column("source_file",  sa.String(255),  nullable=True),
        sa.Column("ingested_at",  sa.DateTime,     server_default=sa.func.now()),
        sa.Column("updated_at",   sa.DateTime,     server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )

    op.create_index("ix_inventory_dealer",       "vehicle_inventory", ["dealer_id"])
    op.create_index("ix_inventory_make",         "vehicle_inventory", ["make"])
    op.create_index("ix_inventory_model",        "vehicle_inventory", ["model"])
    op.create_index("ix_inventory_year",         "vehicle_inventory", ["year"])
    op.create_index("ix_inventory_status",       "vehicle_inventory", ["stock_status"])
    op.create_index("ix_inventory_needs_review", "vehicle_inventory", ["needs_review"])

    # ── validation_errors ──────────────────────────────────────
    op.create_table(
        "validation_errors",
        sa.Column("id",           sa.Integer,      primary_key=True, autoincrement=True),
        sa.Column("raw_row",      JSON,            nullable=False),
        sa.Column("error_detail", sa.Text,         nullable=False),
        sa.Column("source_file",  sa.String(255),  nullable=True),
        sa.Column("row_number",   sa.Integer,      nullable=True),
        sa.Column("created_at",   sa.DateTime,     server_default=sa.func.now()),
    )

    # ── bookings ───────────────────────────────────────────────
    op.create_table(
        "bookings",
        sa.Column("id",                   UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("vehicle_vin",          sa.String(17),  nullable=False),
        sa.Column("customer_name",        sa.String(100), nullable=False),
        sa.Column("customer_email",       sa.String(255), nullable=False),
        sa.Column("customer_phone",       sa.String(30),  nullable=False),
        sa.Column("appointment_datetime", sa.DateTime,    nullable=False),
        sa.Column("notes",                sa.Text,        nullable=True),
        sa.Column("status",               sa.String(20),  nullable=False,
                  server_default="pending"),
        sa.Column("created_at",           sa.DateTime,    server_default=sa.func.now()),
        sa.Column("updated_at",           sa.DateTime,    server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )

    op.create_index("ix_bookings_vin",    "bookings", ["vehicle_vin"])
    op.create_index("ix_bookings_status", "bookings", ["status"])

    # Enable pgcrypto for gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")