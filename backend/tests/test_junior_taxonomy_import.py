"""Junior-high taxonomy import + legacy purge service tests."""
import json

import pytest
from sqlalchemy import func, select

from app.models.activity_log import ActivityLog
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question, QuestionType, question_knowledge_points
from app.models.subject import Subject
from app.models.tag import Tag
from app.models.taxonomy import (
    KnowledgePointTaxonomy,
    TaxonomyPrerequisite,
    TaxonomyStandard,
    TaxonomyTopicStandard,
)
from app.services import junior_taxonomy_service as svc


def _dataset() -> dict:
    topics = [
        {
            "id": "cnm_001",
            "name": "有理数",
            "domain": "数与代数",
            "grade": 7,
            "semester": "上",
            "chapter": "七上 第一章",
            "type": "conceptual",
            "external": False,
            "standards": [{"id": "cms-2022:4.NA.01", "confidence": "exact"}],
        },
        {
            "id": "cnm_002",
            "name": "整式",
            "domain": "数与代数",
            "grade": 7,
            "semester": "上",
            "chapter": "七上 第二章",
            "type": "conceptual",
            "external": False,
            "standards": [{"id": "cms-2022:4.NA.01", "confidence": "inferred"}],
        },
    ]
    deps = [
        {
            "topicId": "cnm_002",
            "prerequisiteId": "cnm_001",
            "strength": "hard",
            "reason": "先有理数后整式",
        }
    ]
    return {
        "topics": topics,
        "topic_by_id": {t["id"]: t for t in topics},
        "junior_topics": topics,
        "junior_ids": {"cnm_001", "cnm_002"},
        "primary_ids": set(),
        "dependencies": deps,
        "internal_edges": deps,
        "cross_stage_edges": [],
        "standards": [
            {
                "id": "cms-2022:4.NA.01",
                "domain": "数与代数",
                "section": "数与运算",
                "clause": "(1)",
                "text": "标准原文",
                "verbatim": False,
            }
        ],
        "aliases": {},
        "mapping": None,
        "include_cross_stage": False,
    }


def _package(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for name in (
        "topics.json",
        "dependencies.json",
        "cn-curriculum-standards.json",
        "id-aliases.json",
    ):
        (data / name).write_text(json.dumps({}), encoding="utf-8")
    return tmp_path


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _subject(db) -> Subject:
    subject = Subject(name="初三数学", slug="jr-math")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject


async def test_import_is_idempotent_and_rolls_back(db_session, tmp_path):
    subject = await _subject(db_session)
    package = _package(tmp_path)

    first = await svc.import_package(
        db_session,
        _dataset(),
        package_dir=package,
        subject_id=subject.id,
        strict_scope=False,
    )
    assert first["summary"]["topics_inserted"] == 2
    assert first["summary"]["prerequisites_inserted"] == 1
    assert first["summary"]["topic_standards_inserted"] == 2
    assert await _count(db_session, KnowledgePoint) == 2
    assert await _count(db_session, KnowledgePointTaxonomy) == 2
    assert await _count(db_session, TaxonomyPrerequisite) == 1
    assert await _count(db_session, TaxonomyStandard) == 1
    assert await _count(db_session, TaxonomyTopicStandard) == 2
    await db_session.refresh(subject)
    assert subject.name == "初中数学"

    second = await svc.import_package(
        db_session,
        _dataset(),
        package_dir=package,
        subject_id=subject.id,
        strict_scope=False,
    )
    assert second["change_count"] == 0
    assert await _count(db_session, KnowledgePoint) == 2
    assert await _count(db_session, TaxonomyPrerequisite) == 1

    rolled = await svc.rollback_batch(db_session, first["batch_id"])
    assert rolled["status"] == "rolled_back"
    assert await _count(db_session, KnowledgePoint) == 0
    assert await _count(db_session, KnowledgePointTaxonomy) == 0
    assert await _count(db_session, TaxonomyPrerequisite) == 0
    assert await _count(db_session, TaxonomyStandard) == 0
    assert await _count(db_session, TaxonomyTopicStandard) == 0


async def test_import_failure_rolls_back_everything(db_session, tmp_path):
    subject = await _subject(db_session)
    dataset = _dataset()
    dataset["internal_edges"] = [
        {"topicId": "cnm_999", "prerequisiteId": "cnm_001", "strength": "hard"}
    ]

    with pytest.raises(KeyError):
        await svc.import_package(
            db_session,
            dataset,
            package_dir=_package(tmp_path),
            subject_id=subject.id,
            strict_scope=False,
        )

    assert await _count(db_session, KnowledgePoint) == 0
    assert await _count(db_session, TaxonomyPrerequisite) == 0
    assert await _count(db_session, TaxonomyStandard) == 0


async def test_purge_legacy_removes_questions_and_points_but_keeps_logs(
    db_session,
):
    subject = await _subject(db_session)
    kp = KnowledgePoint(name="旧知识点", slug="old-kp", subject_id=subject.id)
    db_session.add(kp)
    await db_session.flush()
    question = Question(
        content='{"type":"doc","content":[]}',
        q_type=QuestionType.SINGLE_CHOICE,
        subject_id=subject.id,
        status="published",
    )
    db_session.add(question)
    await db_session.flush()
    db_session.add(Tag(name="旧标签", subject_id=subject.id))
    await db_session.flush()
    await db_session.execute(
        question_knowledge_points.insert().values(
            question_id=question.id, knowledge_point_id=kp.id
        )
    )
    db_session.add(
        ActivityLog(
            action="create",
            resource_type="question",
            resource_id=question.id,
            details={"message": "created"},
        )
    )
    await db_session.commit()

    preview = await svc.purge_legacy(
        db_session, subject_id=subject.id, subject_name="初中数学", dry_run=True
    )
    assert preview["counts"]["legacy_knowledge_points"] == 1
    assert preview["counts"]["legacy_questions"] == 1
    assert preview["counts"]["question_links"] == 1

    applied = await svc.purge_legacy(
        db_session, subject_id=subject.id, subject_name="初中数学", dry_run=False
    )
    assert applied["mode"] == "apply"
    assert await _count(db_session, Question) == 0
    assert await _count(db_session, KnowledgePoint) == 0
    assert await _count(db_session, question_knowledge_points) == 0
    # No FK to the deleted entities: the audit log must survive.
    assert await _count(db_session, ActivityLog) == 1
    await db_session.refresh(subject)
    assert subject.name == "初中数学"
