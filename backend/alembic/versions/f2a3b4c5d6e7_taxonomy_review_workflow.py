"""taxonomy review workflow: mapping targets + question link review

Revision ID: d4e5f6a7b8c9
Revises: a66fc95be990
Create Date: 2026-11-11 14:00:00.000000

Additive only: creates the one-to-many target table and the per-link migration
table with independent review fields.  Existing taxonomy tables are untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "a66fc95be990"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_mapping_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["mapping_id"],
            ["taxonomy_topic_mappings.id"],
            name=op.f("fk_taxonomy_mapping_targets_mapping_id_taxonomy_topic_mappings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"],
            ["knowledge_points.id"],
            name=op.f("fk_taxonomy_mapping_targets_knowledge_point_id_knowledge_points"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["user.id"],
            name=op.f("fk_taxonomy_mapping_targets_reviewed_by_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_mapping_targets")),
        sa.UniqueConstraint(
            "mapping_id", "knowledge_point_id", name="uq_mapping_target"
        ),
    )
    with op.batch_alter_table("taxonomy_mapping_targets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_taxonomy_mapping_targets_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_mapping_targets_mapping_id"),
            ["mapping_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_mapping_targets_knowledge_point_id"),
            ["knowledge_point_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_mapping_target_status", ["mapping_id", "review_status"], unique=False
        )

    op.create_table(
        "taxonomy_question_link_migrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("legacy_knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("new_knowledge_point_id", sa.Integer(), nullable=True),
        sa.Column(
            "result", sa.String(length=32), nullable=False, server_default="pending_review"
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("depends_on_mapping_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["taxonomy_import_batches.id"],
            name=op.f("fk_taxonomy_question_link_migrations_batch_id_taxonomy_import_batches"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_taxonomy_question_link_migrations_question_id_questions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_knowledge_point_id"],
            ["knowledge_points.id"],
            name=op.f("fk_taxonomy_question_link_migrations_legacy_knowledge_point_id_knowledge_points"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_knowledge_point_id"],
            ["knowledge_points.id"],
            name=op.f("fk_taxonomy_question_link_migrations_new_knowledge_point_id_knowledge_points"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_mapping_id"],
            ["taxonomy_topic_mappings.id"],
            name=op.f("fk_taxonomy_question_link_migrations_depends_on_mapping_id_taxonomy_topic_mappings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["user.id"],
            name=op.f("fk_taxonomy_question_link_migrations_reviewed_by_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_question_link_migrations")),
        sa.UniqueConstraint(
            "question_id",
            "legacy_knowledge_point_id",
            name="uq_qlm_question_legacy",
        ),
    )
    with op.batch_alter_table("taxonomy_question_link_migrations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_taxonomy_question_link_migrations_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_question_link_migrations_batch_id"),
            ["batch_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_question_link_migrations_question_id"),
            ["question_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_question_link_migrations_legacy_knowledge_point_id"),
            ["legacy_knowledge_point_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_question_link_migrations_new_knowledge_point_id"),
            ["new_knowledge_point_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_taxonomy_question_link_migrations_depends_on_mapping_id"),
            ["depends_on_mapping_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_qlm_review_status", ["review_status"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("taxonomy_question_link_migrations", schema=None) as batch_op:
        batch_op.drop_index("ix_qlm_review_status")
        batch_op.drop_index(
            batch_op.f("ix_taxonomy_question_link_migrations_depends_on_mapping_id")
        )
        batch_op.drop_index(
            batch_op.f("ix_taxonomy_question_link_migrations_new_knowledge_point_id")
        )
        batch_op.drop_index(
            batch_op.f("ix_taxonomy_question_link_migrations_legacy_knowledge_point_id")
        )
        batch_op.drop_index(
            batch_op.f("ix_taxonomy_question_link_migrations_question_id")
        )
        batch_op.drop_index(batch_op.f("ix_taxonomy_question_link_migrations_batch_id"))
        batch_op.drop_index(batch_op.f("ix_taxonomy_question_link_migrations_id"))
    op.drop_table("taxonomy_question_link_migrations")

    with op.batch_alter_table("taxonomy_mapping_targets", schema=None) as batch_op:
        batch_op.drop_index("ix_mapping_target_status")
        batch_op.drop_index(
            batch_op.f("ix_taxonomy_mapping_targets_knowledge_point_id")
        )
        batch_op.drop_index(batch_op.f("ix_taxonomy_mapping_targets_mapping_id"))
        batch_op.drop_index(batch_op.f("ix_taxonomy_mapping_targets_id"))
    op.drop_table("taxonomy_mapping_targets")
