"""Stage-3 taxonomy integration tables.

These tables are additive: existing ``knowledge_points`` / ``question_knowledge_points``
are not modified.  External IDs live only in ``taxonomy_*`` tables.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class TaxonomySource(Base):
    __tablename__ = "taxonomy_sources"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(64), nullable=False)
    repo_url = Column(String(512), nullable=False)
    commit_sha = Column(String(40), nullable=False)
    data_version = Column(String(64), nullable=True)
    license_status = Column(String(32), nullable=False, default="unconfirmed")
    license_note = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    retrieved_at = Column(DateTime, nullable=True)
    content_hash = Column(String(64), nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("slug", "commit_sha", name="uq_taxonomy_sources_slug_commit"),
    )


class TaxonomyExternalTopic(Base):
    __tablename__ = "taxonomy_external_topics"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_id = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(64), nullable=True)
    grade = Column(SmallInteger, nullable=True)
    semester = Column(String(8), nullable=True)
    chapter = Column(String(255), nullable=True)
    topic_type = Column(String(32), nullable=True)
    description = Column(Text, nullable=True)
    mastery_criteria = Column(JSON, nullable=True)
    external = Column(Boolean, nullable=False, default=False)
    parent_external_id = Column(String(64), nullable=True)
    raw = Column(JSON, nullable=True)
    content_hash = Column(String(64), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_id", name="uq_taxonomy_external_source_external"
        ),
        UniqueConstraint("source_id", "id", name="uq_taxonomy_external_source_id"),
        Index("ix_taxonomy_external_source_grade", "source_id", "grade", "semester"),
        Index("ix_taxonomy_external_source_domain", "source_id", "domain"),
    )


class TaxonomyImportBatch(Base):
    __tablename__ = "taxonomy_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mode = Column(String(16), nullable=False, default="dry_run")
    status = Column(String(16), nullable=False, default="draft")
    summary = Column(JSON, nullable=True)
    conflicts = Column(JSON, nullable=True)
    created_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    rollback_of_batch_id = Column(
        Integer,
        ForeignKey(
            "taxonomy_import_batches.id",
            ondelete="SET NULL",
            name="fk_taxonomy_batches_rollback",
        ),
        nullable=True,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_taxonomy_batches_source_status", "source_id", "status"),
        Index("ix_taxonomy_batches_rollback_of", "rollback_of_batch_id"),
    )


class TaxonomyTopicMapping(Base):
    __tablename__ = "taxonomy_topic_mappings"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, nullable=False)
    external_topic_id = Column(Integer, nullable=False)
    internal_knowledge_point_id = Column(Integer, nullable=True)
    match_type = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=True)
    reason = Column(Text, nullable=False, default="")
    conflict = Column(Boolean, nullable=False, default=False)
    high_risk = Column(Boolean, nullable=False, default=False)
    risk = Column(String(64), nullable=True)
    review_status = Column(String(32), nullable=False, default="pending_review")
    reviewed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime, nullable=True)
    batch_id = Column(
        Integer, ForeignKey("taxonomy_import_batches.id", ondelete="SET NULL"), nullable=True
    )
    revision = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(
        Integer, ForeignKey("taxonomy_topic_mappings.id", ondelete="SET NULL"), nullable=True
    )
    is_current = Column(Boolean, nullable=False, default=True)
    current_key = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id"],
            ["taxonomy_sources.id"],
            name="fk_ttm_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_id", "external_topic_id"],
            ["taxonomy_external_topics.source_id", "taxonomy_external_topics.id"],
            name="fk_ttm_source_external",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["internal_knowledge_point_id"],
            ["knowledge_points.id"],
            name="fk_ttm_internal",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "source_id",
            "external_topic_id",
            "internal_knowledge_point_id",
            "revision",
            name="uq_ttm_source_external_internal_revision",
        ),
        CheckConstraint(
            "(match_type = 'new_topic' AND internal_knowledge_point_id IS NULL) "
            "OR (match_type <> 'new_topic' AND internal_knowledge_point_id IS NOT NULL)",
            name="ck_ttm_new_topic_internal",
        ),
        Index("ix_ttm_source_status_current", "source_id", "review_status", "is_current"),
        Index("ix_ttm_internal_status", "internal_knowledge_point_id", "review_status"),
        Index("ix_ttm_batch", "batch_id"),
        Index("ix_ttm_supersedes", "supersedes_id"),
    )


class TaxonomyPrerequisite(Base):
    __tablename__ = "taxonomy_prerequisites"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prerequisite_knowledge_point_id = Column(
        Integer,
        ForeignKey(
            "knowledge_points.id",
            ondelete="CASCADE",
            name="fk_taxonomy_prereq_prerequisite",
        ),
        nullable=False,
        index=True,
    )
    external_topic_id = Column(String(64), nullable=True)
    external_prerequisite_id = Column(String(64), nullable=True)
    strength = Column(String(8), nullable=False, default="hard")
    raw_evidence = Column(JSON, nullable=True)
    review_status = Column(String(32), nullable=False, default="pending_review")
    reviewed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime, nullable=True)
    batch_id = Column(
        Integer, ForeignKey("taxonomy_import_batches.id", ondelete="SET NULL"), nullable=True
    )
    revision = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(
        Integer, ForeignKey("taxonomy_prerequisites.id", ondelete="SET NULL"), nullable=True
    )
    is_current = Column(Boolean, nullable=False, default=True)
    current_key = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "knowledge_point_id <> prerequisite_knowledge_point_id",
            name="ck_taxonomy_prerequisites_not_self",
        ),
        Index(
            "ix_taxonomy_prereq_source_status",
            "source_id",
            "review_status",
            "is_current",
        ),
        Index("ix_taxonomy_prereq_batch", "batch_id"),
        Index("ix_taxonomy_prereq_supersedes", "supersedes_id"),
    )


class TaxonomyStandard(Base):
    __tablename__ = "taxonomy_standards"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    standard_id = Column(String(64), nullable=False, index=True)
    domain = Column(String(64), nullable=True)
    section = Column(String(255), nullable=True)
    clause = Column(String(64), nullable=True)
    content = Column(Text, nullable=False)
    page_or_ref = Column(String(128), nullable=True)
    verbatim = Column(Boolean, nullable=True)
    text_status = Column(String(255), nullable=True)
    default_confidence = Column(String(16), nullable=True)
    revision = Column(String(64), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id", "standard_id", name="uq_taxonomy_standards_source_standard"
        ),
        UniqueConstraint("source_id", "id", name="uq_taxonomy_standards_source_id"),
        Index("ix_taxonomy_standards_source_domain", "source_id", "domain"),
    )


class TaxonomyTopicStandard(Base):
    __tablename__ = "taxonomy_topic_standards"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_id = Column(Integer, nullable=False)
    confidence = Column(String(16), nullable=False, default="exact")
    review_status = Column(String(32), nullable=False, default="pending_review")
    reviewed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime, nullable=True)
    batch_id = Column(
        Integer, ForeignKey("taxonomy_import_batches.id", ondelete="SET NULL"), nullable=True
    )
    revision = Column(Integer, nullable=False, default=1, server_default=text("1"))
    supersedes_id = Column(
        Integer,
        ForeignKey(
            "taxonomy_topic_standards.id",
            ondelete="SET NULL",
            name="fk_tts_supersedes",
        ),
        nullable=True,
    )
    is_current = Column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    current_key = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "standard_id"],
            ["taxonomy_standards.source_id", "taxonomy_standards.id"],
            name="fk_tts_source_standard",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "source_id",
            "knowledge_point_id",
            "standard_id",
            "revision",
            name="uq_tts_source_internal_standard_revision",
        ),
        Index("ix_taxonomy_topic_standards_standard", "standard_id"),
        Index("ix_taxonomy_topic_standards_batch", "batch_id"),
        Index("ix_tts_current", "source_id", "review_status", "is_current"),
        Index("ix_tts_supersedes", "supersedes_id"),
    )


class TaxonomyExternalRelation(Base):
    __tablename__ = "taxonomy_external_relations"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    topic_external_id = Column(String(64), nullable=False, index=True)
    prerequisite_external_id = Column(String(64), nullable=False, index=True)
    strength = Column(String(8), nullable=False, default="hard")
    relation_kind = Column(String(16), nullable=False, default="internal")
    reason = Column(Text, nullable=True)
    raw = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "topic_external_id",
            "prerequisite_external_id",
            "relation_kind",
            name="uq_taxonomy_ext_rel_source_edge",
        ),
        Index("ix_taxonomy_ext_rel_source_kind", "source_id", "relation_kind"),
        Index("ix_taxonomy_ext_rel_prereq", "prerequisite_external_id"),
    )


class TaxonomyExternalTopicStandard(Base):
    __tablename__ = "taxonomy_external_topic_standards"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_topic_id = Column(String(64), nullable=False, index=True)
    standard_id = Column(String(64), nullable=False, index=True)
    confidence = Column(String(16), nullable=False, default="exact")
    review_status = Column(String(32), nullable=False, default="pending_review")
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_topic_id",
            "standard_id",
            name="uq_taxonomy_ext_topic_standard",
        ),
        Index("ix_taxonomy_ext_topic_std_standard", "source_id", "standard_id"),
    )


class TaxonomyImportChange(Base):
    __tablename__ = "taxonomy_import_changes"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(
        Integer,
        ForeignKey("taxonomy_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type = Column(String(64), nullable=False)
    entity_pk = Column(String(128), nullable=False)
    operation = Column(String(16), nullable=False)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_taxonomy_change_batch_entity", "batch_id", "entity_type"),
    )


class TaxonomyMappingTarget(Base):
    """Explicit targets for one-to-many mappings.

    The primary target is also stored on ``taxonomy_topic_mappings`` so the
    existing single-target code paths keep working.  Extra targets live here.
    Removing a target is done by setting ``review_status='rejected'`` so the
    audit trail is preserved.
    """

    __tablename__ = "taxonomy_mapping_targets"

    id = Column(Integer, primary_key=True, index=True)
    mapping_id = Column(
        Integer,
        ForeignKey("taxonomy_topic_mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_primary = Column(Boolean, nullable=False, default=False)
    review_status = Column(String(32), nullable=False, default="pending_review")
    reviewed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "mapping_id", "knowledge_point_id", name="uq_mapping_target"
        ),
        Index("ix_mapping_target_status", "mapping_id", "review_status"),
    )


class TaxonomyQuestionLinkMigration(Base):
    """Per-link migration outcome plus an independent review state.

    ``result`` records what the migration did; ``review_status`` records the
    human decision.  They are intentionally independent: reviewing a link never
    mutates ``knowledge_points`` or ``question_knowledge_points``.
    """

    __tablename__ = "taxonomy_question_link_migrations"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(
        Integer,
        ForeignKey("taxonomy_import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Frozen copy of the question so the audit survives question deletion.
    question_snapshot = Column(JSON, nullable=True)
    legacy_knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Frozen copy of the legacy row so the audit survives its deletion.
    legacy_snapshot = Column(JSON, nullable=True)
    new_knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    result = Column(String(32), nullable=False, default="pending_review")
    reason = Column(Text, nullable=True)
    review_status = Column(String(32), nullable=False, default="pending_review")
    reviewed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    depends_on_mapping_id = Column(
        Integer,
        ForeignKey("taxonomy_topic_mappings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "legacy_knowledge_point_id",
            name="uq_qlm_question_legacy",
        ),
        Index("ix_qlm_review_status", "review_status"),
    )

class KnowledgePointTaxonomy(Base):
    """Formal knowledge-point metadata imported from the external taxonomy.

    The knowledge point itself lives in ``knowledge_points`` and keeps the
    QuestionBank auto-increment primary key.  This table stores the external
    stable id plus the queryable grade/semester/chapter/domain metadata.
    """

    __tablename__ = "knowledge_point_taxonomy"

    knowledge_point_id = Column(
        Integer,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id = Column(
        Integer,
        ForeignKey("taxonomy_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_topic_id = Column(String(64), nullable=True)
    stage = Column(String(16), nullable=True)
    grade = Column(SmallInteger, nullable=True)
    semester = Column(String(8), nullable=True)
    chapter = Column(String(255), nullable=True)
    domain = Column(String(64), nullable=True)
    is_legacy = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    knowledge_point = relationship("KnowledgePoint", back_populates="taxonomy_meta")

    __table_args__ = (
        UniqueConstraint("source_id", "external_topic_id", name="uq_kpt_external"),
        Index("ix_kpt_stage_grade", "stage", "grade", "semester"),
        Index("ix_kpt_domain", "domain"),
    )
