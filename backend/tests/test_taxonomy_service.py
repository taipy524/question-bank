import pytest
from sqlalchemy import select

from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.taxonomy import TaxonomyPrerequisite, TaxonomyTopicStandard
from app.services import taxonomy_service as service


async def _subject(db, name="数学", slug="math"):
    subject = Subject(name=name, slug=slug)
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject


async def _kp(db, subject, name, slug):
    row = KnowledgePoint(name=name, slug=slug, subject_id=subject.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _source(db):
    return await service.create_source(
        db,
        slug="cn-math-taxonomy",
        repo_url="https://github.com/xiaoyang111222/cn-math-taxonomy",
        commit_sha="cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab",
        content_hash="fee361e7",
    )


async def _prereq_row(db, source, topic_id, prerequisite_id, status="pending_review"):
    row = TaxonomyPrerequisite(
        source_id=source.id,
        knowledge_point_id=topic_id,
        prerequisite_knowledge_point_id=prerequisite_id,
        external_topic_id=f"e{topic_id}",
        external_prerequisite_id=f"e{prerequisite_id}",
        strength="hard",
        review_status=status,
        revision=1,
        is_current=True,
        current_key=service._prereq_key(source.id, topic_id, prerequisite_id),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _standard_link(db, source, standard_id, kp_id, confidence="exact", status="pending_review"):
    row = TaxonomyTopicStandard(
        source_id=source.id,
        knowledge_point_id=kp_id,
        standard_id=standard_id,
        confidence=confidence,
        review_status=status,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Mapping review
# ---------------------------------------------------------------------------
async def test_mapping_review_revision_and_history(db_session):
    subject = await _subject(db_session)
    kp = await _kp(db_session, subject, "二元一次方程组", "binary")
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_093", name="三元一次方程组"
    )
    mapping = await service.create_mapping(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
        match_type="semantic",
        confidence=0.714,
        high_risk=True,
        risk="confusable_single_char:三->二",
    )

    with pytest.raises(service.TaxonomyError):
        await service.review_mapping(
            db_session, mapping_id=mapping.id, action="confirm", reviewer_id=None
        )
    confirmed = await service.review_mapping(
        db_session,
        mapping_id=mapping.id,
        action="confirm",
        reviewer_id=None,
        comment="manual review",
        acknowledge_high_risk=True,
    )
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["revision"] == 2
    history = await service.mapping_history(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
    )
    assert [row["review_status"] for row in history] == ["pending_review", "confirmed"]

    undone = await service.review_mapping(
        db_session, mapping_id=confirmed["id"], action="undo", reviewer_id=None, comment="undo"
    )
    assert undone["review_status"] == "pending_review"
    assert undone["revision"] == 3
    current = await service.list_mappings(db_session, source_id=source.id, include_history=False)
    assert len(current) == 1
    assert current[0]["review_status"] == "pending_review"


async def test_mapping_reject_is_kept(db_session):
    subject = await _subject(db_session)
    kp = await _kp(db_session, subject, "函数", "function")
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_999", name="函数初步"
    )
    mapping = await service.create_mapping(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
        match_type="semantic",
        confidence=0.6,
    )
    rejected = await service.review_mapping(
        db_session, mapping_id=mapping.id, action="reject", reviewer_id=None, comment="no"
    )
    assert rejected["review_status"] == "rejected"
    history = await service.mapping_history(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
    )
    assert len(history) == 2


# ---------------------------------------------------------------------------
# New-topic review
# ---------------------------------------------------------------------------
async def test_new_topic_approval_creates_one_knowledge_point(db_session):
    subject = await _subject(db_session)
    parent = await _kp(db_session, subject, "数与式", "shu")
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_001", name="正数与负数的概念"
    )
    mapping = await service.create_mapping(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=None,
        match_type="new_topic",
        review_status="new_topic_pending",
    )
    before = (await service.list_new_topics(db_session, source_id=source.id))
    assert len(before) == 1

    result = await service.approve_new_topic(
        db_session,
        mapping_id=mapping.id,
        reviewer_id=None,
        subject_id=subject.id,
        parent_id=parent.id,
        comment="approved",
    )
    assert result["knowledge_point"]["name"] == "正数与负数的概念"
    assert result["mapping"]["review_status"] == "confirmed"
    assert await service.list_new_topics(db_session, source_id=source.id) == []
    kp = await db_session.get(KnowledgePoint, result["knowledge_point"]["id"])
    assert kp is not None and kp.parent_id == parent.id

    # A duplicate name must not be created twice.
    topic2 = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_002", name="正数与负数的概念"
    )
    mapping2 = await service.create_mapping(
        db_session,
        source_id=source.id,
        external_topic_id=topic2.id,
        internal_knowledge_point_id=None,
        match_type="new_topic",
        review_status="new_topic_pending",
    )
    with pytest.raises(service.TaxonomyError):
        await service.approve_new_topic(
            db_session,
            mapping_id=mapping2.id,
            reviewer_id=None,
            subject_id=subject.id,
            parent_id=parent.id,
        )


async def test_new_topic_reject(db_session):
    subject = await _subject(db_session)
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_003", name="无关主题"
    )
    mapping = await service.create_mapping(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=None,
        match_type="new_topic",
        review_status="new_topic_pending",
    )
    row = await service.reject_new_topic(
        db_session, mapping_id=mapping.id, reviewer_id=None, comment="not needed"
    )
    assert row["review_status"] == "rejected"


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
async def test_prerequisite_review_and_cycle_guard(db_session):
    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a")
    b = await _kp(db_session, subject, "乙", "b")
    c = await _kp(db_session, subject, "丙", "c")
    source = await _source(db_session)
    ab = await _prereq_row(db_session, source, a.id, b.id)
    bc = await _prereq_row(db_session, source, b.id, c.id)
    ca = await _prereq_row(db_session, source, c.id, a.id)

    reviewed = await service.review_prerequisite(
        db_session, prerequisite_id=ab.id, action="confirm", reviewer_id=None
    )
    assert reviewed["reviewed_by"] is None
    assert reviewed["reviewed_at"] is not None
    assert reviewed["revision"] == 2
    await service.review_prerequisite(
        db_session, prerequisite_id=bc.id, action="confirm", reviewer_id=None
    )
    with pytest.raises(service.TaxonomyError):
        await service.review_prerequisite(
            db_session, prerequisite_id=ca.id, action="confirm", reviewer_id=None
        )
    conflicts = await service.prerequisite_conflicts(db_session, source_id=source.id)
    assert any(item["type"] == "cycle" for item in conflicts)


async def test_prerequisite_self_loop_is_rejected_by_database(db_session):
    from sqlalchemy.exc import IntegrityError

    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a")
    source = await _source(db_session)
    row = TaxonomyPrerequisite(
        source_id=source.id,
        knowledge_point_id=a.id,
        prerequisite_knowledge_point_id=a.id,
        strength="hard",
        is_current=True,
        current_key=f"self:{a.id}",
    )
    db_session.add(row)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# Standards
# ---------------------------------------------------------------------------
async def test_standard_link_review_keeps_confidence(db_session):
    subject = await _subject(db_session)
    kp = await _kp(db_session, subject, "函数", "function")
    source = await _source(db_session)
    standard = await service.upsert_standard(
        db_session,
        source_id=source.id,
        standard_id="cms-2022:4.NA.01",
        content="标准原文",
        domain="数与代数",
        default_confidence="exact",
    )
    link = await _standard_link(
        db_session, source, standard.id, kp.id, confidence="inferred"
    )
    reviewed = await service.review_topic_standard(
        db_session, link_id=link.id, action="confirm", reviewer_id=None
    )
    assert reviewed["review_status"] == "confirmed"
    assert reviewed["confidence"] == "inferred"
    assert reviewed["revision"] == 2
    assert reviewed["reviewed_at"] is not None
    history = await service.list_topic_standards(
        db_session, source_id=source.id, current_only=False
    )
    assert [row["review_status"] for row in history] == ["pending_review", "confirmed"]


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------
async def test_batch_preview_execute_idempotent_and_rollback(db_session):
    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a")
    b = await _kp(db_session, subject, "乙", "b")
    source = await _source(db_session)
    standard = await service.upsert_standard(
        db_session,
        source_id=source.id,
        standard_id="cms-2022:4.NA.01",
        content="标准原文",
        domain="数与代数",
    )
    prereq = await _prereq_row(db_session, source, a.id, b.id)
    link = await _standard_link(db_session, source, standard.id, a.id)
    before_ids = sorted(row.id for row in (await db_session.execute(select(KnowledgePoint))).scalars().all())

    preview = await service.preview_batch(db_session, source_id=source.id)
    assert preview["summary"]["pending_prerequisites"] == 1
    assert preview["summary"]["pending_standard_links"] == 1

    dry = await service.create_batch(
        db_session, source_id=source.id, mode="dry_run", user_id=None
    )
    with pytest.raises(service.TaxonomyError):
        await service.execute_batch(db_session, batch_id=dry.id)

    batch = await service.create_batch(
        db_session, source_id=source.id, mode="apply", user_id=None
    )
    applied = await service.execute_batch(db_session, batch_id=batch.id)
    assert applied["change_count"] == 2
    assert applied["status"] == "applied"
    confirmed_prereq = await db_session.get(TaxonomyPrerequisite, prereq.id)
    confirmed_link = await db_session.get(TaxonomyTopicStandard, link.id)
    assert confirmed_prereq.review_status == "confirmed"
    assert confirmed_prereq.reviewed_at is not None
    assert confirmed_link.review_status == "confirmed"
    assert confirmed_link.reviewed_at is not None

    again = await service.execute_batch(db_session, batch_id=batch.id)
    assert again["change_count"] == 0

    rolled = await service.rollback_batch(db_session, batch_id=batch.id, user_id=None)
    assert rolled["restored_changes"] == 2
    rolled_prereq = await db_session.get(TaxonomyPrerequisite, prereq.id)
    rolled_link = await db_session.get(TaxonomyTopicStandard, link.id)
    assert rolled_prereq.review_status == "pending_review"
    assert rolled_prereq.reviewed_at is None
    assert rolled_link.review_status == "pending_review"
    assert rolled_link.reviewed_at is None
    with pytest.raises(service.TaxonomyError):
        await service.rollback_batch(db_session, batch_id=batch.id)

    after_ids = sorted(row.id for row in (await db_session.execute(select(KnowledgePoint))).scalars().all())
    assert before_ids == after_ids


async def test_batch_execution_blocked_by_prerequisite_cycle(db_session):
    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a")
    b = await _kp(db_session, subject, "乙", "b")
    source = await _source(db_session)
    await _prereq_row(db_session, source, a.id, b.id)
    await _prereq_row(db_session, source, b.id, a.id)
    preview = await service.preview_batch(db_session, source_id=source.id)
    assert preview["summary"]["prerequisite_conflicts"] >= 1
    batch = await service.create_batch(
        db_session, source_id=source.id, mode="apply", user_id=None
    )
    with pytest.raises(service.TaxonomyError):
        await service.execute_batch(db_session, batch_id=batch.id)


async def test_stale_review_cannot_overwrite_newer_revision(db_session):
    subject = await _subject(db_session)
    kp = await _kp(db_session, subject, "函数", "fn-stale")
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm-stale", name="函数初步"
    )
    mapping = await service.create_mapping(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
        match_type="semantic",
        confidence=0.7,
    )
    confirmed = await service.review_mapping(
        db_session, mapping_id=mapping.id, action="confirm", reviewer_id=None
    )
    with pytest.raises(service.TaxonomyError):
        await service.review_mapping(
            db_session, mapping_id=mapping.id, action="reject", reviewer_id=None
        )
    current = await service.get_mapping(db_session, confirmed["id"])
    assert current.review_status == "confirmed"


async def test_batch_mid_execution_failure_is_not_committed(db_session, engine):
    from unittest import mock
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a-fail")
    b = await _kp(db_session, subject, "乙", "b-fail")
    source = await _source(db_session)
    prereq = await _prereq_row(db_session, source, a.id, b.id)
    prereq_id = prereq.id
    batch = await service.create_batch(
        db_session, source_id=source.id, mode="apply", user_id=None
    )
    batch_id = batch.id
    with mock.patch.object(service, "_now", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            await service.execute_batch(db_session, batch_id=batch_id)
    await db_session.rollback()
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as fresh:
        row = await fresh.get(TaxonomyPrerequisite, prereq_id)
        saved_batch = await fresh.get(service.TaxonomyImportBatch, batch_id)
        assert row.review_status == "pending_review"
        assert saved_batch.status == "validated"


async def test_rollback_only_affects_current_batch(db_session):
    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a-b1")
    b = await _kp(db_session, subject, "乙", "b-b1")
    c = await _kp(db_session, subject, "丙", "c-b1")
    source = await _source(db_session)
    first = await _prereq_row(db_session, source, a.id, b.id)
    batch1 = await service.create_batch(db_session, source_id=source.id, mode="apply", user_id=None)
    await service.execute_batch(db_session, batch_id=batch1.id)
    second = await _prereq_row(db_session, source, b.id, c.id)
    batch2 = await service.create_batch(db_session, source_id=source.id, mode="apply", user_id=None)
    await service.execute_batch(db_session, batch_id=batch2.id)

    await service.rollback_batch(db_session, batch_id=batch1.id)
    assert (await db_session.get(TaxonomyPrerequisite, first.id)).review_status == "pending_review"
    assert (await db_session.get(TaxonomyPrerequisite, second.id)).review_status == "confirmed"


async def test_second_batch_is_idempotent_when_first_already_applied(db_session):
    subject = await _subject(db_session)
    a = await _kp(db_session, subject, "甲", "a-idem")
    b = await _kp(db_session, subject, "乙", "b-idem")
    source = await _source(db_session)
    await _prereq_row(db_session, source, a.id, b.id)
    batch1 = await service.create_batch(db_session, source_id=source.id, mode="apply", user_id=None)
    batch2 = await service.create_batch(db_session, source_id=source.id, mode="apply", user_id=None)
    first = await service.execute_batch(db_session, batch_id=batch1.id)
    second = await service.execute_batch(db_session, batch_id=batch2.id)
    assert first["change_count"] == 1
    assert second["change_count"] == 0
