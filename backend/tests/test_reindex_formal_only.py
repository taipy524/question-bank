"""Reindex must cover formal knowledge points only and require an explicit scope."""
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.vector_store import VectorStore
from app.crud.crud_knowledge_point import knowledge_point as crud_kp
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.taxonomy import KnowledgePointTaxonomy


async def _seed(db):
    subject = Subject(name="初中数学", slug="reindex-math")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)

    formal1 = KnowledgePoint(name="有理数", slug="cnm-001", subject_id=subject.id)
    formal2 = KnowledgePoint(name="整式", slug="cnm-002", subject_id=subject.id)
    legacy = KnowledgePoint(name="旧知识点", slug="legacy-001", subject_id=subject.id)
    db.add_all([formal1, formal2, legacy])
    await db.commit()
    for kp in (formal1, formal2, legacy):
        await db.refresh(kp)

    db.add_all(
        [
            KnowledgePointTaxonomy(
                knowledge_point_id=formal1.id, is_legacy=False, is_active=True
            ),
            KnowledgePointTaxonomy(
                knowledge_point_id=formal2.id, is_legacy=False, is_active=True
            ),
        ]
    )
    await db.commit()
    return subject, formal1, formal2, legacy


async def test_subject_reindex_removes_legacy_and_adds_formal_only(db_session):
    subject, formal1, formal2, legacy = await _seed(db_session)
    deleted: list[int] = []
    upserted: list[dict] = []

    with patch.object(
        VectorStore, "is_available", classmethod(lambda cls: True)
    ), patch.object(
        VectorStore,
        "delete_knowledge_points_batch",
        classmethod(lambda cls, ids: deleted.extend(ids)),
    ), patch.object(
        VectorStore,
        "upsert_knowledge_points_batch",
        classmethod(lambda cls, items, raise_on_error=False: upserted.extend(items)),
    ):
        count = await crud_kp.reindex_vectors(db_session, subject_id=subject.id)

    assert count == 2
    # The delete list must include the legacy id so its stale vector is removed.
    assert set(deleted) == {formal1.id, formal2.id, legacy.id}
    assert {item["id"] for item in upserted} == {formal1.id, formal2.id}


async def test_unscoped_reindex_is_rejected(db_session):
    with patch.object(VectorStore, "is_available", classmethod(lambda cls: True)):
        with pytest.raises(ValueError):
            await crud_kp.reindex_vectors(db_session)


async def test_full_reindex_resets_collection_and_excludes_legacy(db_session):
    subject, formal1, formal2, legacy = await _seed(db_session)
    reset: list[bool] = []
    upserted: list[dict] = []

    with patch.object(
        VectorStore, "is_available", classmethod(lambda cls: True)
    ), patch.object(
        VectorStore, "reset_collection", classmethod(lambda cls: reset.append(True))
    ), patch.object(
        VectorStore,
        "upsert_knowledge_points_batch",
        classmethod(lambda cls, items, raise_on_error=False: upserted.extend(items)),
    ):
        count = await crud_kp.reindex_vectors(db_session, full=True)

    assert reset == [True]
    assert count == 2
    assert {item["id"] for item in upserted} == {formal1.id, formal2.id}
