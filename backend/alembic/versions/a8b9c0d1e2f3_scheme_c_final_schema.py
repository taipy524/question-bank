"""scheme C: final knowledge-point taxonomy schema and audit snapshots

Revision ID: a8b9c0d1e2f3
Revises: f2a3b4c5d6e7
Create Date: 2026-11-11 15:00:00.000000

DESIGN DRAFT for Scheme C.  Additive only.

Creates the knowledge-point metadata table and the optional legacy-mapping
audit tables.  The simplified deployment does not build a historical activity
log snapshot system: ``activity_logs`` rows are kept as-is and have no foreign
key to the deleted entities.

NOT EXECUTED against production.  Stage 3 must run it against an isolated test
MySQL first (Alembic upgrade + downgrade + data migration + rollback).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------- KP metadata
    op.create_table(
        "knowledge_point_taxonomy",
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("external_topic_id", sa.String(length=64), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.Column("semester", sa.String(length=8), nullable=True),
        sa.Column("chapter", sa.String(length=255), nullable=True),
        sa.Column("domain", sa.String(length=64), nullable=True),
        sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"],
            ["knowledge_points.id"],
            name=op.f("fk_knowledge_point_taxonomy_knowledge_point_id_knowledge_points"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["taxonomy_sources.id"],
            name=op.f("fk_knowledge_point_taxonomy_source_id_taxonomy_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "knowledge_point_id", name=op.f("pk_knowledge_point_taxonomy")
        ),
        sa.UniqueConstraint(
            "source_id", "external_topic_id", name="uq_kpt_external"
        ),
    )
    with op.batch_alter_table("knowledge_point_taxonomy", schema=None) as batch_op:
        batch_op.create_index(
            "ix_kpt_stage_grade", ["stage", "grade", "semester"], unique=False
        )
        batch_op.create_index("ix_kpt_domain", ["domain"], unique=False)

    # ---------------------------------------------------------------- legacy mapping
    op.create_table(
        "taxonomy_legacy_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        # nullable so the row can outlive the legacy knowledge point
        sa.Column("legacy_knowledge_point_id", sa.Integer(), nullable=True),
        sa.Column("new_knowledge_point_id", sa.Integer(), nullable=True),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("high_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=True),
        # frozen copy of the legacy row so the audit survives deletion
        sa.Column("legacy_snapshot", sa.JSON(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["taxonomy_import_batches.id"],
            name=op.f("fk_taxonomy_legacy_mappings_batch_id_taxonomy_import_batches"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_knowledge_point_id"],
            ["knowledge_points.id"],
            name=op.f("fk_taxonomy_legacy_mappings_legacy_knowledge_point_id_knowledge_points"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["new_knowledge_point_id"],
            ["knowledge_points.id"],
            name=op.f("fk_taxonomy_legacy_mappings_new_knowledge_point_id_knowledge_points"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["user.id"],
            name=op.f("fk_taxonomy_legacy_mappings_reviewed_by_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_legacy_mappings")),
        sa.UniqueConstraint(
            "legacy_knowledge_point_id", name="uq_legacy_kp"
        ),
    )
    with op.batch_alter_table("taxonomy_legacy_mappings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_taxonomy_legacy_mappings_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_legacy_mappings_legacy_knowledge_point_id"),
            ["legacy_knowledge_point_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_legacy_mappings_new_knowledge_point_id"),
            ["new_knowledge_point_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_legacy_review", ["review_status", "match_type"], unique=False
        )

    # ---------------------------------------------------------------- link audit survival
    # Allow question-link migration rows to outlive the legacy knowledge point.
    with op.batch_alter_table(
        "taxonomy_question_link_migrations", schema=None
    ) as batch_op:
        batch_op.alter_column(
            "legacy_knowledge_point_id", existing_type=sa.Integer(), nullable=True
        )
        batch_op.add_column(sa.Column("legacy_snapshot", sa.JSON(), nullable=True))
        batch_op.alter_column(
            "question_id", existing_type=sa.Integer(), nullable=True
        )
        batch_op.add_column(sa.Column("question_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(
        "taxonomy_question_link_migrations", schema=None
    ) as batch_op:
        batch_op.drop_column("question_snapshot")
        batch_op.alter_column(
            "question_id", existing_type=sa.Integer(), nullable=False
        )
        batch_op.drop_column("legacy_snapshot")
        batch_op.alter_column(
            "legacy_knowledge_point_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    # Dropping the tables removes their indexes and FKs automatically; dropping
    # indexes explicitly fails on MySQL when the index backs a foreign key.
    op.drop_table("taxonomy_legacy_mappings")
    op.drop_table("knowledge_point_taxonomy")
