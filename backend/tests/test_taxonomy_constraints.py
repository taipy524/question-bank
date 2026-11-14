import pytest
from sqlalchemy.exc import IntegrityError

from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.subject import Subject
from app.models.taxonomy import (
    TaxonomyExternalTopic,
    TaxonomyPrerequisite,
    TaxonomySource,
    TaxonomyStandard,
    TaxonomyTopicMapping,
    TaxonomyTopicStandard,
)


async def _source(db, slug="s1", commit="a" * 40):
    row = TaxonomySource(slug=slug, repo_url="https://example.test", commit_sha=commit)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _subject(db):
    subject = Subject(name="数学", slug="math-c")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    kp = KnowledgePoint(name="函数", slug="fn-c", subject_id=subject.id)
    db.add(kp)
    await db.commit()
    await db.refresh(kp)
    return subject, kp


async def _topic(db, source, external_id="cnm_001"):
    row = TaxonomyExternalTopic(
        source_id=source.id, external_id=external_id, name="外部节点", raw={}
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def test_external_topic_unique_per_source(db_session):
    source = await _source(db_session)
    await _topic(db_session, source)
    db_session.add(
        TaxonomyExternalTopic(source_id=source.id, external_id="cnm_001", name="重复")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_mapping_new_topic_check(db_session):
    source = await _source(db_session)
    subject, kp = await _subject(db_session)
    topic = await _topic(db_session, source)
    db_session.add(
        TaxonomyTopicMapping(
            source_id=source.id,
            external_topic_id=topic.id,
            internal_knowledge_point_id=kp.id,
            match_type="new_topic",
            review_status="pending_review",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_mapping_source_consistency_composite_fk(db_session):
    source1 = await _source(db_session, slug="s1")
    source2 = await _source(db_session, slug="s2", commit="b" * 40)
    topic = await _topic(db_session, source1)
    subject, kp = await _subject(db_session)
    db_session.add(
        TaxonomyTopicMapping(
            source_id=source2.id,
            external_topic_id=topic.id,
            internal_knowledge_point_id=kp.id,
            match_type="exact",
            review_status="pending_review",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_mapping_current_key_unique(db_session):
    source = await _source(db_session)
    subject, kp = await _subject(db_session)
    topic = await _topic(db_session, source)
    for revision in (1, 2):
        db_session.add(
            TaxonomyTopicMapping(
                source_id=source.id,
                external_topic_id=topic.id,
                internal_knowledge_point_id=kp.id,
                match_type="exact",
                review_status="pending_review",
                revision=revision,
                is_current=True,
                current_key=f"m:{source.id}:{topic.id}:{kp.id}",
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_prerequisite_self_loop_check(db_session):
    source = await _source(db_session)
    subject, kp = await _subject(db_session)
    db_session.add(
        TaxonomyPrerequisite(
            source_id=source.id,
            knowledge_point_id=kp.id,
            prerequisite_knowledge_point_id=kp.id,
            strength="hard",
            is_current=True,
            current_key=f"p:{source.id}:{kp.id}:{kp.id}",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_standard_link_source_consistency(db_session):
    source1 = await _source(db_session, slug="s1")
    source2 = await _source(db_session, slug="s2", commit="b" * 40)
    subject, kp = await _subject(db_session)
    standard = TaxonomyStandard(
        source_id=source1.id, standard_id="std-1", content="标准"
    )
    db_session.add(standard)
    await db_session.commit()
    await db_session.refresh(standard)
    db_session.add(
        TaxonomyTopicStandard(
            source_id=source2.id,
            knowledge_point_id=kp.id,
            standard_id=standard.id,
            confidence="exact",
            review_status="pending_review",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_existing_knowledge_points_and_questions_are_not_modified(db_session):
    subject, kp = await _subject(db_session)
    question = Question(
        content='{"type":"doc","content":[]}',
        q_type="single_choice",
        options=[],
        answer='{}',
        subject_id=subject.id,
        created_by=None,
    )
    db_session.add(question)
    await db_session.commit()
    await db_session.refresh(question)
    kp_id = kp.id
    question_id = question.id
    source = await _source(db_session)
    topic = await _topic(db_session, source)
    mapping = TaxonomyTopicMapping(
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp_id,
        match_type="exact",
        review_status="confirmed",
        current_key=f"m:{source.id}:{topic.id}:{kp_id}",
    )
    db_session.add(mapping)
    await db_session.commit()
    db_session.expire_all()
    assert (await db_session.get(KnowledgePoint, kp_id)) is not None
    assert (await db_session.get(Question, question_id)) is not None
