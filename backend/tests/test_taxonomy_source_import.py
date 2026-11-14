import copy

import pytest
from sqlalchemy import func, select

from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.taxonomy import (
    TaxonomyExternalRelation,
    TaxonomyExternalTopic,
    TaxonomyExternalTopicStandard,
    TaxonomyImportBatch,
    TaxonomySource,
    TaxonomyStandard,
    TaxonomyTopicMapping,
)
from app.services import taxonomy_source_import as importer

REAL_SOURCE = "/workspace/.opencode/tmp/cn-math-taxonomy-cf73951"


def _dataset(kp_id: int) -> dict:
    topics = [
        {
            "id": "cnm_001",
            "name": "外部甲",
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
            "name": "外部乙",
            "domain": "图形与几何",
            "grade": 8,
            "semester": "下",
            "chapter": "八下 第一章",
            "type": "procedural",
            "external": False,
            "standards": [{"id": "cms-2022:4.NA.01", "confidence": "inferred"}],
        },
        {"id": "cnm_p001", "name": "小学先修", "domain": "数与代数", "grade": 4, "semester": "上", "external": False},
        {"id": "cnm_s001", "name": "高中节点", "domain": "数与代数", "grade": 10, "semester": "上", "external": False},
    ]
    dependencies = [
        {"topicId": "cnm_002", "prerequisiteId": "cnm_001", "strength": "hard", "reason": "r1"},
        {"topicId": "cnm_001", "prerequisiteId": "cnm_p001", "strength": "soft", "reason": "cross"},
        {"topicId": "cnm_s001", "prerequisiteId": "cnm_002", "strength": "soft", "reason": "senior"},
    ]
    standards = [
        {
            "id": "cms-2022:4.NA.01",
            "domain": "数与代数",
            "section": "数与运算",
            "clause": "(1)",
            "text": "标准原文",
            "page_or_ref": "p18",
            "verbatim": False,
            "text_status": "synthetic",
        }
    ]
    mapping = {
        "external_topics": [
            {
                "external_id": "cnm_001",
                "match_type": "exact",
                "review_status": "pending_review",
                "candidates": [
                    {
                        "internal_id": kp_id,
                        "internal_name": "内部甲",
                        "confidence": 0.9,
                        "reason": "exact",
                        "high_risk": False,
                        "risk": None,
                        "conflict": False,
                    }
                ],
            },
            {
                "external_id": "cnm_002",
                "match_type": "new_topic",
                "review_status": "new_topic_pending",
                "candidates": [],
                "reason": "no candidate",
            },
        ]
    }
    dataset = {
        "topics": topics,
        "topic_by_id": {topic["id"]: topic for topic in topics},
        "junior_topics": [topics[0], topics[1]],
        "junior_ids": {"cnm_001", "cnm_002"},
        "primary_ids": {"cnm_p001"},
        "dependencies": dependencies,
        "internal_edges": [dependencies[0]],
        "cross_stage_edges": [dependencies[1]],
        "standards": standards,
        "aliases": {},
        "mapping": mapping,
    }
    return dataset


async def _seed(db):
    subject = Subject(name="数学", slug="math-import")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    kp = KnowledgePoint(name="内部甲", slug="kp-import", subject_id=subject.id)
    db.add(kp)
    await db.commit()
    await db.refresh(kp)
    return subject, kp


def _meta(commit="a" * 40):
    return {
        "repo_url": "https://example.test/repo",
        "commit_sha": commit,
        "data_version": "test",
        "license_status": "synthetic-test",
        "license_note": "synthetic only",
        "content_hash": "hash",
    }


async def _count(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_preview_and_full_import_idempotent_and_rollback(db_session):
    subject, kp = await _seed(db_session)
    dataset = _dataset(kp.id)
    before_kp = await _count(db_session, KnowledgePoint)

    preview = await importer.import_dataset(
        db_session,
        dataset,
        source_meta=_meta(),
        mapping=dataset["mapping"],
        mode="preview",
        strict_counts=False,
    )
    assert preview["database_writes"] == 0
    assert preview["counts"]["topics_to_import"] == 2
    assert preview["validation"]["errors"] == []

    first = await importer.import_dataset(
        db_session,
        dataset,
        source_meta=_meta(),
        mapping=dataset["mapping"],
        strict_counts=False,
    )
    assert first["change_count"] > 0
    assert await _count(db_session, TaxonomyExternalTopic) == 2
    assert await _count(db_session, TaxonomyStandard) == 1
    assert await _count(db_session, TaxonomyExternalRelation) == 2
    assert await _count(db_session, TaxonomyExternalTopicStandard) == 2
    assert await _count(db_session, TaxonomyTopicMapping) == 2
    assert await _count(db_session, KnowledgePoint) == before_kp

    mappings = (await db_session.execute(select(TaxonomyTopicMapping))).scalars().all()
    assert all(row.review_status in {"pending_review", "new_topic_pending"} for row in mappings)
    assert any(row.match_type == "new_topic" and row.internal_knowledge_point_id is None for row in mappings)

    second = await importer.import_dataset(
        db_session,
        dataset,
        source_meta=_meta(),
        mapping=dataset["mapping"],
        strict_counts=False,
    )
    assert second["change_count"] == 0
    assert await _count(db_session, TaxonomyExternalTopic) == 2

    result = await importer.rollback_source_batch(db_session, batch_id=first["batch_id"])
    assert result["status"] == "rolled_back"
    assert await _count(db_session, TaxonomyExternalTopic) == 0
    assert await _count(db_session, TaxonomyStandard) == 0
    assert await _count(db_session, TaxonomyExternalRelation) == 0
    assert await _count(db_session, TaxonomyExternalTopicStandard) == 0
    assert await _count(db_session, TaxonomyTopicMapping) == 0
    # Source rows are retained for audit/version history.
    assert await _count(db_session, TaxonomySource) == 1
    assert await _count(db_session, KnowledgePoint) == before_kp


async def test_failure_is_transactional(db_session):
    subject, kp = await _seed(db_session)
    dataset = _dataset(kp.id)
    dataset["mapping"]["external_topics"][0]["candidates"][0]["internal_id"] = 999999
    with pytest.raises(importer.DatasetError):
        await importer.import_dataset(
            db_session,
            dataset,
            source_meta=_meta(),
            mapping=dataset["mapping"],
            strict_counts=False,
        )
    assert await _count(db_session, TaxonomySource) == 0
    assert await _count(db_session, TaxonomyExternalTopic) == 0
    assert await _count(db_session, TaxonomyStandard) == 0
    assert await _count(db_session, TaxonomyTopicMapping) == 0


async def test_cross_source_isolation(db_session):
    subject, kp = await _seed(db_session)
    first_dataset = _dataset(kp.id)
    second_dataset = copy.deepcopy(first_dataset)
    first = await importer.import_dataset(
        db_session, first_dataset, source_slug="source-a", source_meta=_meta("a" * 40),
        mapping=first_dataset["mapping"], strict_counts=False,
    )
    second = await importer.import_dataset(
        db_session, second_dataset, source_slug="source-b", source_meta=_meta("b" * 40),
        mapping=second_dataset["mapping"], strict_counts=False,
    )
    await importer.rollback_source_batch(db_session, batch_id=first["batch_id"])
    remaining = (await db_session.execute(select(TaxonomySource))).scalars().all()
    assert {row.slug for row in remaining} == {"source-a", "source-b"}
    # Only source-b's external data remains after rolling back source-a.
    topics = (await db_session.execute(select(TaxonomyExternalTopic))).scalars().all()
    source_b = next(row for row in remaining if row.slug == "source-b")
    assert {row.source_id for row in topics} == {source_b.id}
    assert len(topics) == 2
    assert second["status"] == "applied"


def test_real_dataset_validation_without_database():
    import os
    if not os.path.isdir(REAL_SOURCE):
        pytest.skip("real source data not available")
    dataset = importer.load_dataset(
        REAL_SOURCE, "/workspace/repos/question-bank-taipy/reports/mapping_result.json"
    )
    report = importer.validate_dataset(dataset, strict_counts=True)
    assert report["errors"] == []
    assert report["counts"]["junior_topics"] == 315
    assert report["counts"]["internal_edges"] == 563
    assert report["counts"]["cross_stage_edges"] == 45
    assert report["counts"]["standards"] == 157
    assert report["counts"]["standard_refs"] == 383
    assert report["counts"]["mapping_candidates"] == 12
    assert report["counts"]["new_topic_rows"] == 303


async def test_external_queries_after_import(db_session):
    subject, kp = await _seed(db_session)
    dataset = _dataset(kp.id)
    result = await importer.import_dataset(
        db_session, dataset, source_meta=_meta(), mapping=dataset["mapping"], strict_counts=False
    )
    topics = await importer.list_external_topics(db_session)
    assert len(topics) == 2
    assert {row["external_id"] for row in topics} == {"cnm_001", "cnm_002"}
    relations = await importer.list_external_relations(db_session)
    assert len(relations) == 2
    assert {row["relation_kind"] for row in relations} == {"internal", "cross_stage"}
    refs = await importer.list_external_topic_standards(db_session)
    assert len(refs) == 2
    assert {row["confidence"] for row in refs} == {"exact", "inferred"}
    assert result["status"] == "applied"


def test_pilot_subset_is_deterministic():
    dataset = _dataset(1)
    subset, mapping = importer.subset_dataset(dataset, 1, dataset["mapping"])
    assert [topic["id"] for topic in subset["junior_topics"]] == ["cnm_001"]
    assert len(subset["internal_edges"]) == 0
    assert len(subset["cross_stage_edges"]) == 1
    assert len(subset["standards"]) == 1
    assert mapping is not None
    assert [row["external_id"] for row in mapping["external_topics"]] == ["cnm_001"]
