"""taste_profile_redesign

Feature 021: Replace EMA taste model with signal_counts + summary + chips.
Phase A: Reshape interaction_log -> interactions (new enum, drop columns, rename).
Phase B: Reshape taste_model (drop EMA columns, add JSONB columns, change PK).

Revision ID: f4d8e1a23c56
Revises: c7e3a8d12b90
Create Date: 2026-04-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f4d8e1a23c56"
down_revision: str | None = "c7e3a8d12b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Phase A: interaction_log -> interactions
    # ------------------------------------------------------------------

    # A1. Map onboarding_explicit rows to confirm / dismiss
    op.execute(
        """
        UPDATE interaction_log
        SET signal_type = CASE
            WHEN context->>'confirmed' = 'true'
                THEN 'onboarding_confirm'
            ELSE 'onboarding_dismiss'
        END
        WHERE signal_type = 'onboarding_explicit'
        """
    )

    # A2. Delete rows where place_id IS NULL
    op.execute("DELETE FROM interaction_log WHERE place_id IS NULL")

    # A3. Drop gain and context columns
    op.drop_column("interaction_log", "gain")
    op.drop_column("interaction_log", "context")

    # A4. Rename table
    op.rename_table("interaction_log", "interactions")

    # A5. Rename column signal_type -> type
    op.alter_column(
        "interactions", "signal_type", new_column_name="type"
    )

    # A6. Replace enum — drop default first (old enum default blocks cast)
    op.execute(
        "ALTER TABLE interactions ALTER COLUMN type DROP DEFAULT"
    )
    op.execute(
        "CREATE TYPE interactiontype AS ENUM "
        "('save','accepted','rejected',"
        "'onboarding_confirm','onboarding_dismiss')"
    )
    op.execute(
        "ALTER TABLE interactions "
        "ALTER COLUMN type TYPE interactiontype "
        "USING type::text::interactiontype"
    )
    op.execute("DROP TYPE IF EXISTS signaltype")

    # A7. Alter place_id to NOT NULL
    op.alter_column("interactions", "place_id", nullable=False)

    # A8. Drop UUID PK, add BIGSERIAL PK
    op.drop_constraint(
        "interaction_log_pkey", "interactions", type_="primary"
    )
    op.drop_column("interactions", "id")
    op.add_column(
        "interactions",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False
        ),
    )
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS interactions_id_seq "
        "OWNED BY interactions.id"
    )
    op.execute(
        "ALTER TABLE interactions "
        "ALTER COLUMN id SET DEFAULT nextval('interactions_id_seq')"
    )
    op.execute(
        "SELECT setval('interactions_id_seq', "
        "COALESCE(MAX(id), 0) + 1, false) FROM interactions"
    )
    # Backfill existing rows with sequential IDs
    op.execute(
        "UPDATE interactions SET id = nextval('interactions_id_seq')"
    )
    op.create_primary_key("interactions_pkey", "interactions", ["id"])

    # A9. Drop old indexes and add new composite indexes
    op.drop_index(
        "ix_interaction_log_user_id",
        table_name="interactions",
        if_exists=True,
    )
    op.create_index(
        "ix_interactions_user_type",
        "interactions",
        ["user_id", "type"],
    )
    op.create_index(
        "ix_interactions_user_created",
        "interactions",
        ["user_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # Phase B: taste_model reshape
    # ------------------------------------------------------------------

    # B1. Drop old columns
    op.drop_column("taste_model", "model_version")
    op.drop_column("taste_model", "parameters")
    op.drop_column("taste_model", "confidence")
    op.drop_column("taste_model", "interaction_count")
    op.drop_column("taste_model", "eval_score")
    op.drop_column("taste_model", "created_at")
    op.drop_column("taste_model", "updated_at")

    # B2. Change PK from id to user_id
    op.drop_constraint(
        "taste_model_pkey", "taste_model", type_="primary"
    )
    op.drop_column("taste_model", "id")
    op.drop_index(
        "ix_taste_model_user_id",
        table_name="taste_model",
        if_exists=True,
    )
    # No separate unique constraint — uniqueness was via the index above
    op.create_primary_key(
        "taste_model_pkey", "taste_model", ["user_id"]
    )

    # B3. Add new columns
    op.add_column(
        "taste_model",
        sa.Column(
            "taste_profile_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "signal_counts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "chips",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "generated_from_log_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse Phase B: taste_model
    # ------------------------------------------------------------------
    op.drop_column("taste_model", "generated_from_log_count")
    op.drop_column("taste_model", "generated_at")
    op.drop_column("taste_model", "chips")
    op.drop_column("taste_model", "signal_counts")
    op.drop_column("taste_model", "taste_profile_summary")

    # Restore old PK structure
    op.drop_constraint(
        "taste_model_pkey", "taste_model", type_="primary"
    )
    op.add_column(
        "taste_model",
        sa.Column("id", sa.String(), nullable=False),
    )
    op.create_primary_key(
        "taste_model_pkey", "taste_model", ["id"]
    )
    op.create_index(
        "ix_taste_model_user_id",
        "taste_model",
        ["user_id"],
        unique=True,
    )

    # Restore dropped columns with defaults
    op.add_column(
        "taste_model",
        sa.Column(
            "model_version",
            sa.String(),
            nullable=False,
            server_default=sa.text("'v0'"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "interaction_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column("eval_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "taste_model",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # ------------------------------------------------------------------
    # Reverse Phase A: interactions -> interaction_log
    # ------------------------------------------------------------------
    op.drop_index(
        "ix_interactions_user_created", table_name="interactions"
    )
    op.drop_index(
        "ix_interactions_user_type", table_name="interactions"
    )

    # Restore old enum
    op.execute(
        "CREATE TYPE signaltype AS ENUM "
        "('save','accepted','rejected','ignored',"
        "'repeat_visit','search_accepted','onboarding_explicit')"
    )
    op.execute(
        "ALTER TABLE interactions "
        "ALTER COLUMN type TYPE signaltype "
        "USING type::text::signaltype"
    )
    op.execute("DROP TYPE IF EXISTS interactiontype")

    # Rename column and table back
    op.alter_column(
        "interactions", "type", new_column_name="signal_type"
    )
    op.rename_table("interactions", "interaction_log")

    # Restore columns
    op.add_column(
        "interaction_log",
        sa.Column(
            "gain",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )
    op.add_column(
        "interaction_log",
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Restore UUID PK
    op.drop_constraint(
        "interactions_pkey", "interaction_log", type_="primary"
    )
    op.drop_column("interaction_log", "id")
    op.add_column(
        "interaction_log",
        sa.Column(
            "id",
            postgresql.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_primary_key(
        "interaction_log_pkey", "interaction_log", ["id"]
    )

    # Make place_id nullable again
    op.alter_column("interaction_log", "place_id", nullable=True)

    # Restore old index
    op.create_index(
        "ix_interaction_log_user_id",
        "interaction_log",
        ["user_id"],
    )
