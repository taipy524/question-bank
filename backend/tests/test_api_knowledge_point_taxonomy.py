"""Knowledge-point taxonomy metadata + prerequisite/standard API tests."""
import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.taxonomy import (
    KnowledgePointTaxonomy,
    TaxonomyPrerequisite,
    TaxonomySource,
    TaxonomyStandard,
    TaxonomyTopicStandard,
)
from app.models.user import User

API = "/api/v1"


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def _seed(db):
    user = User(
        username="kp_taxonomy",
        hashed_password="x",
        is_active=True,
        is_superuser=True,
    )
    subject = Subject(name="初中数学", slug="jr-api")
    db.add_all([user, subject])
    await db.commit()
    await db.refresh(user)
    await db.refresh(subject)

    kp1 = KnowledgePoint(name="有理数", slug="cnm-001", subject_id=subject.id)
    kp2 = KnowledgePoint(name="整式", slug="cnm-002", subject_id=subject.id)
    legacy = KnowledgePoint(name="旧知识点", slug="legacy-001", subject_id=subject.id)
    db.add_all([kp1, kp2, legacy])
    await db.commit()
    await db.refresh(kp1)
    await db.refresh(kp2)
    await db.refresh(legacy)

    source = TaxonomySource(
        slug="test-source",
        repo_url="https://example.test/repo",
        commit_sha="cf73951",
        license_status="confirmed",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    db.add_all(
        [
            KnowledgePointTaxonomy(
                knowledge_point_id=kp1.id,
                source_id=source.id,
                external_topic_id="cnm_001",
                stage="初中",
                grade=7,
                semester="上",
                chapter="七上 第一章",
                domain="数与代数",
            ),
            KnowledgePointTaxonomy(
                knowledge_point_id=kp2.id,
                source_id=source.id,
                external_topic_id="cnm_002",
                stage="初中",
                grade=8,
                semester="下",
                chapter="八下 第一章",
                domain="图形与几何",
            ),
            TaxonomyStandard(
                source_id=source.id,
                standard_id="cms-2022:4.NA.01",
                domain="数与代数",
                content="标准原文",
            ),
        ]
    )
    await db.commit()
    standard = (
        await db.execute(
            select(TaxonomyStandard).where(
                TaxonomyStandard.standard_id == "cms-2022:4.NA.01"
            )
        )
    ).scalar_one()

    db.add(
        TaxonomyPrerequisite(
            source_id=source.id,
            knowledge_point_id=kp2.id,
            prerequisite_knowledge_point_id=kp1.id,
            external_topic_id="cnm_002",
            external_prerequisite_id="cnm_001",
            strength="hard",
            review_status="confirmed",
            revision=1,
            is_current=True,
            current_key="p:test:1",
        )
    )
    db.add(
        TaxonomyTopicStandard(
            source_id=source.id,
            knowledge_point_id=kp1.id,
            standard_id=standard.id,
            confidence="exact",
            review_status="confirmed",
            revision=1,
            is_current=True,
            current_key="s:test:1",
        )
    )
    await db.commit()
    return user, subject, kp1, kp2, legacy


@pytest.mark.asyncio
async def test_list_returns_taxonomy_metadata_and_filters(client, db_session):
    user, subject, kp1, kp2, legacy = await _seed(db_session)
    headers = _auth(user)

    response = await client.get(
        f"{API}/knowledge-points", params={"subject_id": subject.id}, headers=headers
    )
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()}
    assert items[kp1.id]["grade"] == 7
    assert items[kp1.id]["semester"] == "上"
    assert items[kp1.id]["chapter"] == "七上 第一章"
    assert items[kp1.id]["domain"] == "数与代数"
    assert items[kp1.id]["is_formal"] is True
    assert items[kp2.id]["is_formal"] is True
    assert items[legacy.id]["is_formal"] is False

    response = await client.get(
        f"{API}/knowledge-points",
        params={"subject_id": subject.id, "grade": 8},
        headers=headers,
    )
    assert [item["id"] for item in response.json()] == [kp2.id]

    response = await client.get(
        f"{API}/knowledge-points",
        params={"subject_id": subject.id, "domain": "数与代数", "semester": "上"},
        headers=headers,
    )
    assert [item["id"] for item in response.json()] == [kp1.id]

    response = await client.get(
        f"{API}/knowledge-points",
        params={"subject_id": subject.id, "chapter": "八下 第一章"},
        headers=headers,
    )
    assert [item["id"] for item in response.json()] == [kp2.id]


@pytest.mark.asyncio
async def test_prerequisites_and_standards_endpoints(client, db_session):
    user, subject, kp1, kp2, legacy = await _seed(db_session)
    headers = _auth(user)

    response = await client.get(
        f"{API}/knowledge-points/{kp2.id}/prerequisites", headers=headers
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["prerequisite_id"] == kp1.id
    assert rows[0]["name"] == "有理数"
    assert rows[0]["strength"] == "hard"
    assert rows[0]["grade"] == 7

    response = await client.get(
        f"{API}/knowledge-points/{kp1.id}/prerequisites", headers=headers
    )
    assert response.json() == []

    response = await client.get(
        f"{API}/knowledge-points/{kp1.id}/standards", headers=headers
    )
    assert response.status_code == 200, response.text
    standards = response.json()
    assert len(standards) == 1
    assert standards[0]["standard_id"] == "cms-2022:4.NA.01"
    assert standards[0]["confidence"] == "exact"
    assert standards[0]["content"] == "标准原文"

    response = await client.get(
        f"{API}/knowledge-points/{kp2.id}/standards", headers=headers
    )
    assert response.json() == []


@pytest.mark.asyncio
async def test_manual_create_is_formal_and_gets_metadata(client, db_session):
    user, subject, kp1, kp2, legacy = await _seed(db_session)
    headers = _auth(user)

    response = await client.post(
        f"{API}/knowledge-points",
        json={"name": "手工知识点", "slug": "manual-001", "subject_id": subject.id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["is_formal"] is True
    assert created["grade"] is None

    meta = (
        await db_session.execute(
            select(KnowledgePointTaxonomy).where(
                KnowledgePointTaxonomy.knowledge_point_id == created["id"]
            )
        )
    ).scalar_one_or_none()
    assert meta is not None
    assert meta.source_id is None
    assert meta.is_legacy is False


@pytest.mark.asyncio
async def test_vector_status_counts_formal_only(client, db_session, monkeypatch):
    user, subject, kp1, kp2, legacy = await _seed(db_session)

    from app.core.vector_store import VectorStore

    monkeypatch.setattr(
        VectorStore, "is_available", classmethod(lambda cls: True)
    )
    monkeypatch.setattr(
        VectorStore,
        "count_by_subject",
        classmethod(lambda cls, sid, name="knowledge_points": 2),
    )

    response = await client.get(
        f"{API}/knowledge-points/vector-status",
        params={"subject_id": subject.id},
        headers=_auth(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["db_count"] == 2
    assert body["vector_count"] == 2
    assert body["needs_reindex"] is False
