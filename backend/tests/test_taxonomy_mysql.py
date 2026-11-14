"""Real MySQL validation for the taxonomy migrations.

Skipped unless ``MYSQL_TEST_URL`` points at a dedicated, disposable MySQL
database.  Never point this at the production database: the test upgrades and
downgrades the schema.
"""

import asyncio
import os
import uuid

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.migrations import _alembic_config

MYSQL_TEST_URL = os.getenv("MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(
    not MYSQL_TEST_URL, reason="MYSQL_TEST_URL not set (needs a dedicated MySQL database)"
)

TAXONOMY_TABLES = {
    "taxonomy_sources",
    "taxonomy_external_topics",
    "taxonomy_topic_mappings",
    "taxonomy_prerequisites",
    "taxonomy_standards",
    "taxonomy_topic_standards",
    "taxonomy_import_batches",
    "taxonomy_import_changes",
}


def _sync_url() -> str:
    # Alembic accepts the async driver URL; inspection needs a sync driver.
    return MYSQL_TEST_URL.replace("+aiomysql", "+pymysql").replace("+asyncmy", "+pymysql")


def test_mysql_constraints_and_transactions():
    suffix = uuid.uuid4().hex[:8]
    cfg = _alembic_config(MYSQL_TEST_URL)
    command.upgrade(cfg, "head")
    engine = create_engine(_sync_url())
    try:
        # Unique source version
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO taxonomy_sources (slug, repo_url, commit_sha, license_status, status) "
                "VALUES (:slug, 'https://example.test', REPEAT('a',40), 'unconfirmed', 'active')"
            ), {"slug": f"mysql-uniq-{suffix}"})
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO taxonomy_sources (slug, repo_url, commit_sha, license_status, status) "
                    "VALUES (:slug, 'https://example.test', REPEAT('a',40), 'unconfirmed', 'active')"
                ), {"slug": f"mysql-uniq-{suffix}"})

        # Transaction rollback leaves no row
        with pytest.raises(RuntimeError):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO taxonomy_sources (slug, repo_url, commit_sha, license_status, status) "
                    "VALUES (:slug, 'https://example.test', REPEAT('b',40), 'unconfirmed', 'active')"
                ), {"slug": f"mysql-tx-{suffix}"})
                raise RuntimeError("force rollback")
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM taxonomy_sources WHERE slug=:slug"), {"slug": f"mysql-tx-{suffix}"}).scalar_one()
        assert count == 0
    finally:
        engine.dispose()


def test_mysql_check_and_composite_fk():
    cfg = _alembic_config(MYSQL_TEST_URL)
    suffix = uuid.uuid4().hex[:8]
    command.upgrade(cfg, "head")
    engine = create_engine(_sync_url())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO subjects (name, slug, required_review_count) "
                "VALUES (:name, :slug, 1)"
            ), {"name": f"mysql-math-{suffix}", "slug": f"mysql-math-{suffix}"})
            subject_id = conn.execute(text("SELECT id FROM subjects WHERE slug=:slug"), {"slug": f"mysql-math-{suffix}"}).scalar_one()
            conn.execute(text(
                "INSERT INTO knowledge_points (name, slug, subject_id) "
                "VALUES (:name, :slug, :sid)"
            ), {"name": f"mysql-kp-{suffix}", "slug": f"mysql-kp-{suffix}", "sid": subject_id})
            kp_slug = f"mysql-kp-{suffix}"
            kp_id = conn.execute(text("SELECT id FROM knowledge_points WHERE slug=:slug"), {"slug": kp_slug}).scalar_one()
            conn.execute(text(
                "INSERT INTO taxonomy_sources (slug, repo_url, commit_sha, license_status, status) "
                "VALUES (:slug, 'https://example.test', REPEAT('c',40), 'unconfirmed', 'active')"
            ), {"slug": f"mysql-check-{suffix}"})
            source_id = conn.execute(text("SELECT id FROM taxonomy_sources WHERE slug=:slug"), {"slug": f"mysql-check-{suffix}"}).scalar_one()
            conn.execute(text(
                "INSERT INTO taxonomy_external_topics "
                "(source_id, external_id, name, external, is_active) "
                "VALUES (:sid, :eid, 'check-topic', 0, 1)"
            ), {"sid": source_id, "eid": f"cnm_check_{suffix}"})
            topic_id = conn.execute(text(
                "SELECT id FROM taxonomy_external_topics WHERE source_id=:sid AND external_id=:eid"
            ), {"sid": source_id, "eid": f"cnm_check_{suffix}"}).scalar_one()

        # new_topic must have NULL internal id
        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO taxonomy_topic_mappings "
                    "(source_id, external_topic_id, internal_knowledge_point_id, match_type, reason, "
                    " conflict, high_risk, review_status, revision, is_current) "
                    "VALUES (:sid, :tid, :kid, 'new_topic', '', 0, 0, 'new_topic_pending', 1, 1)"
                ), {"sid": source_id, "tid": topic_id, "kid": kp_id})

        # Composite FK: topic belongs to source, mapping must use the same source
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO taxonomy_sources (slug, repo_url, commit_sha, license_status, status) "
                "VALUES (:slug, 'https://example.test', REPEAT('d',40), 'unconfirmed', 'active')"
            ), {"slug": f"mysql-other-{suffix}"})
            other_id = conn.execute(text("SELECT id FROM taxonomy_sources WHERE slug=:slug"), {"slug": f"mysql-other-{suffix}"}).scalar_one()
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO taxonomy_topic_mappings "
                    "(source_id, external_topic_id, internal_knowledge_point_id, match_type, reason, "
                    " conflict, high_risk, review_status, revision, is_current) "
                    "VALUES (:sid, :tid, :kid, 'semantic', '', 0, 0, 'pending_review', 1, 1)"
                ), {"sid": other_id, "tid": topic_id, "kid": kp_id})
    finally:
        engine.dispose()


async def test_mysql_import_idempotent_and_rollback():
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

    from app.models.knowledge_point import KnowledgePoint
    from app.models.subject import Subject
    from app.models.taxonomy import TaxonomyExternalTopic
    from app.services import taxonomy_source_import as importer
    from tests.test_taxonomy_source_import import _dataset

    cfg = _alembic_config(MYSQL_TEST_URL)
    # Alembic's env.py calls asyncio.run; run it in a worker thread so we do not
    # nest event loops inside this async test.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_async_engine(MYSQL_TEST_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as db:
            suffix = uuid.uuid4().hex[:8]
            subject = Subject(name=f"mysql-{suffix}", slug=f"mysql-{suffix}", required_review_count=1)
            db.add(subject)
            await db.commit()
            await db.refresh(subject)
            kp = KnowledgePoint(name=f"kp-{suffix}", slug=f"kp-{suffix}", subject_id=subject.id)
            db.add(kp)
            await db.commit()
            await db.refresh(kp)
            before = (await db.execute(text("SELECT COUNT(*) FROM knowledge_points"))).scalar_one()
            dataset = _dataset(kp.id)
            meta = {
                "repo_url": "https://example.test",
                "commit_sha": suffix,
                "data_version": "test",
                "license_status": "synthetic-test",
                "license_note": "synthetic",
                "content_hash": "hash",
            }
            first = await importer.import_dataset(
                db, dataset, source_slug=f"mysql-src-{suffix}", source_meta=meta,
                mapping=dataset["mapping"], strict_counts=False,
            )
            assert first["change_count"] > 0
            second = await importer.import_dataset(
                db, dataset, source_slug=f"mysql-src-{suffix}", source_meta=meta,
                mapping=dataset["mapping"], strict_counts=False,
            )
            assert second["change_count"] == 0
            rolled = await importer.rollback_source_batch(db, batch_id=first["batch_id"])
            assert rolled["status"] == "rolled_back"
            after = (await db.execute(text("SELECT COUNT(*) FROM knowledge_points"))).scalar_one()
            assert before == after
    finally:
        await engine.dispose()


def test_mysql_upgrade_downgrade_and_constraints():
    cfg = _alembic_config(MYSQL_TEST_URL)
    command.upgrade(cfg, "head")

    engine = create_engine(_sync_url())
    try:
        inspector = inspect(engine)
        assert TAXONOMY_TABLES <= set(inspector.get_table_names())

        # Current-version uniqueness + composite source foreign keys.
        uniques = {
            constraint["name"]
            for table in ("taxonomy_topic_mappings", "taxonomy_topic_standards")
            for constraint in inspector.get_unique_constraints(table)
        }
        assert "uq_ttm_source_external_internal_revision" in uniques
        assert "uq_tts_source_internal_standard_revision" in uniques
        assert "uq_taxonomy_topic_standards_current_key" in uniques

        checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("taxonomy_topic_mappings")
        }
        assert any(name.endswith("ck_ttm_new_topic_internal") for name in checks)
        prereq_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("taxonomy_prerequisites")
        }
        assert any(name.endswith("ck_taxonomy_prerequisites_not_self") for name in prereq_checks)

        fks = {
            tuple(constraint["constrained_columns"]): constraint["referred_table"]
            for constraint in inspector.get_foreign_keys("taxonomy_topic_mappings")
        }
        assert fks[("source_id", "external_topic_id")] == "taxonomy_external_topics"
    finally:
        engine.dispose()

    with create_engine(_sync_url()).connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    assert current == set(ScriptDirectory.from_config(cfg).get_heads())

    # Downgrade one revision (audit fields) and re-apply.
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
