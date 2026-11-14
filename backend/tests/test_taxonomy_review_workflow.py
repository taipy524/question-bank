import pytest

from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question, QuestionStatus, QuestionType
from app.models.subject import Subject
from app.models.taxonomy import TaxonomyQuestionLinkMigration
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


async def _question(db, subject):
    row = Question(
        content="题干",
        q_type=QuestionType.SINGLE_CHOICE,
        status=QuestionStatus.PUBLISHED,
        subject_id=subject.id,
    )
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


async def _mapping(db, source, topic, kp, match_type="semantic", status="pending_review"):
    return await service.create_mapping(
        db,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
        match_type=match_type,
        confidence=0.6,
        review_status=status,
    )


async def _link(db, question, legacy_kp, new_kp, mapping, review_status="pending_review"):
    row = TaxonomyQuestionLinkMigration(
        question_id=question.id,
        legacy_knowledge_point_id=legacy_kp.id,
        new_knowledge_point_id=new_kp.id,
        result="migrated",
        review_status=review_status,
        depends_on_mapping_id=mapping.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def test_deferred_transition_and_resume(db_session):
    subject = await _subject(db_session)
    kp = await _kp(db_session, subject, "一元一次方程", "linear")
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_041", name="一元一次方程的概念"
    )
    mapping = await _mapping(db_session, source, topic, kp)

    deferred = await service.review_mapping(
        db_session, mapping_id=mapping.id, action="defer", reviewer_id=None, comment="等复核"
    )
    assert deferred["review_status"] == "deferred"
    assert deferred["revision"] == 2

    resumed = await service.review_mapping(
        db_session, mapping_id=deferred["id"], action="reopen", reviewer_id=None
    )
    assert resumed["review_status"] == "pending_review"

    history = await service.mapping_history(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
    )
    assert [r["review_status"] for r in history] == [
        "pending_review",
        "deferred",
        "pending_review",
    ]


async def test_reassign_creates_revision_and_marks_links_stale(db_session):
    subject = await _subject(db_session)
    old_kp = await _kp(db_session, subject, "反比例函数", "inverse")
    new_kp = await _kp(db_session, subject, "正比例函数", "direct")
    question = await _question(db_session, subject)
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_200", name="正比例函数"
    )
    mapping = await _mapping(db_session, source, topic, old_kp)
    link = await _link(db_session, question, old_kp, old_kp, mapping)

    result = await service.reassign_mapping(
        db_session,
        mapping_id=mapping.id,
        internal_knowledge_point_id=new_kp.id,
        reviewer_id=None,
        comment="反比例≠正比例，改选",
    )
    assert result["previous_internal_id"] == old_kp.id
    assert result["new_internal_id"] == new_kp.id
    assert result["mapping"]["revision"] == 2
    assert result["stale_links"] == 1

    refreshed = await db_session.get(TaxonomyQuestionLinkMigration, link.id)
    assert refreshed.review_status == "stale"

    history = await service.mapping_history(
        db_session,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=new_kp.id,
    )
    assert history[-1]["revision"] == 2


async def test_one_to_many_targets_pending_then_confirmed(db_session):
    subject = await _subject(db_session)
    kp_a = await _kp(db_session, subject, "二元一次方程组及其解", "a")
    kp_b = await _kp(db_session, subject, "三元一次方程组", "b")
    kp_c = await _kp(db_session, subject, "一次函数与二元一次方程组", "c")
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_088", name="二元一次方程组及其解"
    )
    mapping = await _mapping(db_session, source, topic, kp_a)

    created = await service.set_mapping_targets(
        db_session,
        mapping_id=mapping.id,
        knowledge_point_ids=[kp_a.id, kp_b.id, kp_c.id],
        reviewer_id=None,
        comment="候选语义待复核",
    )
    assert created["mapping"]["match_type"] == "one_to_many"
    assert created["mapping"]["review_status"] == "pending_review"
    assert len(created["targets"]) == 3
    assert all(t["review_status"] == "pending_review" for t in created["targets"])

    with pytest.raises(service.TaxonomyError):
        await service.confirm_mapping_targets(
            db_session, mapping_id=created["mapping"]["id"], reviewer_id=None
        )

    confirmed = await service.confirm_mapping_targets(
        db_session,
        mapping_id=created["mapping"]["id"],
        reviewer_id=None,
        comment="人工确认三个目标",
    )
    assert confirmed["status"] == "confirmed"
    assert confirmed["approved_targets"] == 3
    assert all(t["review_status"] == "approved" for t in confirmed["targets"])


async def test_question_link_review_actions(db_session):
    subject = await _subject(db_session)
    legacy_kp = await _kp(db_session, subject, "实数与数的运算", "legacy")
    new_kp = await _kp(db_session, subject, "实数的运算", "new")
    question = await _question(db_session, subject)
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_080", name="实数的运算"
    )
    mapping = await _mapping(db_session, source, topic, legacy_kp)
    link = await _link(db_session, question, legacy_kp, new_kp, mapping)

    deferred = await service.review_question_link(
        db_session, link_id=link.id, action="defer", reviewer_id=None, comment="等映射"
    )
    assert deferred["review_status"] == "deferred"
    assert deferred["result"] == "migrated"  # result is independent

    reopened = await service.review_question_link(
        db_session, link_id=link.id, action="reopen", reviewer_id=None
    )
    assert reopened["review_status"] == "pending_review"

    approved = await service.review_question_link(
        db_session, link_id=link.id, action="approve", reviewer_id=None, comment="ok"
    )
    assert approved["review_status"] == "approved"

    rejected = await service.review_question_link(
        db_session, link_id=link.id, action="reject", reviewer_id=None, comment="no"
    )
    assert rejected["review_status"] == "rejected"

    listed = await service.list_question_links(
        db_session, review_status="rejected", question_id=question.id
    )
    assert len(listed) == 1


async def test_approve_link_without_target_requires_comment(db_session):
    subject = await _subject(db_session)
    legacy_kp = await _kp(db_session, subject, "一次函数", "legacy")
    question = await _question(db_session, subject)
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_999", name="一次函数"
    )
    mapping = await _mapping(db_session, source, topic, legacy_kp)
    row = TaxonomyQuestionLinkMigration(
        question_id=question.id,
        legacy_knowledge_point_id=legacy_kp.id,
        new_knowledge_point_id=None,
        result="unmappable",
        review_status="deferred",
        depends_on_mapping_id=mapping.id,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    with pytest.raises(service.TaxonomyError):
        await service.review_question_link(
            db_session, link_id=row.id, action="approve", reviewer_id=None
        )

    approved = await service.review_question_link(
        db_session,
        link_id=row.id,
        action="approve",
        reviewer_id=None,
        comment="确认保留旧关联，不迁移",
    )
    assert approved["review_status"] == "approved"
    assert approved["new_knowledge_point_id"] is None


async def test_deferred_mapping_marks_dependent_links_stale(db_session):
    subject = await _subject(db_session)
    kp = await _kp(db_session, subject, "因式分解", "factor")
    question = await _question(db_session, subject)
    source = await _source(db_session)
    topic = await service.upsert_external_topic(
        db_session, source_id=source.id, external_id="cnm_224", name="因式分解法"
    )
    mapping = await _mapping(db_session, source, topic, kp, status="confirmed")
    link = await _link(db_session, question, kp, kp, mapping, review_status="approved")

    await service.review_mapping(
        db_session, mapping_id=mapping.id, action="defer", reviewer_id=None, comment="暂缓"
    )

    refreshed = await db_session.get(TaxonomyQuestionLinkMigration, link.id)
    assert refreshed.review_status == "stale"
