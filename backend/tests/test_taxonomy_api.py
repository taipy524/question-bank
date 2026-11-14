import pytest

from app.core.security import create_access_token
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.taxonomy import (
    TaxonomyExternalRelation,
    TaxonomyExternalTopicStandard,
    TaxonomyTopicStandard,
)
from app.models.user import User
from app.services import taxonomy_service as service

API = "/api/v1/taxonomy"


async def _user(db, username, is_superuser=False):
    user = User(
        username=username,
        full_name=username,
        hashed_password="x",
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def _seed(db):
    admin = await _user(db, "tax-admin", True)
    reviewer = await _user(db, "tax-reviewer", False)
    subject = Subject(name="数学", slug="math-tax")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    kp = KnowledgePoint(name="二元一次方程组", slug="binary-tax", subject_id=subject.id)
    db.add(kp)
    await db.commit()
    await db.refresh(kp)
    source = await service.create_source(
        db, slug="cn-math-taxonomy", repo_url="https://example.test/repo", commit_sha="c" * 40
    )
    topic = await service.upsert_external_topic(
        db, source_id=source.id, external_id="cnm_093", name="三元一次方程组"
    )
    mapping = await service.create_mapping(
        db,
        source_id=source.id,
        external_topic_id=topic.id,
        internal_knowledge_point_id=kp.id,
        match_type="semantic",
        confidence=0.714,
        high_risk=True,
        risk="confusable_single_char:三->二",
    )
    new_topic = await service.upsert_external_topic(
        db, source_id=source.id, external_id="cnm_001", name="正数与负数的概念"
    )
    new_mapping = await service.create_mapping(
        db,
        source_id=source.id,
        external_topic_id=new_topic.id,
        internal_knowledge_point_id=None,
        match_type="new_topic",
        review_status="new_topic_pending",
    )
    standard = await service.upsert_standard(
        db, source_id=source.id, standard_id="cms-2022:4.NA.01", content="标准", domain="数与代数"
    )
    link = TaxonomyTopicStandard(
        source_id=source.id,
        knowledge_point_id=kp.id,
        standard_id=standard.id,
        confidence="inferred",
        review_status="pending_review",
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return {
        "admin": admin,
        "reviewer": reviewer,
        "subject": subject,
        "kp": kp,
        "source": source,
        "mapping": mapping,
        "new_mapping": new_mapping,
        "link": link,
    }


async def test_mapping_list_and_review_permissions(client, db_session):
    ctx = await _seed(db_session)
    url = f"{API}/mappings?source_id={ctx['source'].id}"
    unauthorized = await client.get(url)
    assert unauthorized.status_code in (401, 403)

    listing = await client.get(url, headers=_auth(ctx["reviewer"]))
    assert listing.status_code == 200
    body = listing.json()
    assert len(body) == 2
    assert body[0]["external"]["external_id"]

    denied = await client.post(
        f"{API}/mappings/{ctx['mapping'].id}/review",
        json={"action": "confirm"},
        headers=_auth(ctx["reviewer"]),
    )
    assert denied.status_code == 400

    high_risk_blocked = await client.post(
        f"{API}/mappings/{ctx['mapping'].id}/review",
        json={"action": "confirm", "comment": "ok"},
        headers=_auth(ctx["admin"]),
    )
    assert high_risk_blocked.status_code == 400

    confirmed = await client.post(
        f"{API}/mappings/{ctx['mapping'].id}/review",
        json={"action": "confirm", "comment": "manual", "acknowledge_high_risk": True},
        headers=_auth(ctx["admin"]),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["review_status"] == "confirmed"


async def test_new_topic_approve_api(client, db_session):
    ctx = await _seed(db_session)
    before = await client.get(f"{API}/new-topics", headers=_auth(ctx["reviewer"]))
    assert before.status_code == 200
    assert len(before.json()) == 1
    response = await client.post(
        f"{API}/new-topics/{ctx['new_mapping'].id}/approve",
        json={"subject_id": ctx["subject"].id, "parent_id": ctx["kp"].id, "comment": "ok"},
        headers=_auth(ctx["admin"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["knowledge_point"]["name"] == "正数与负数的概念"
    after = await client.get(f"{API}/new-topics", headers=_auth(ctx["reviewer"]))
    assert after.json() == []


async def test_standard_link_review_api(client, db_session):
    ctx = await _seed(db_session)
    response = await client.post(
        f"{API}/standard-links/{ctx['link'].id}/review",
        json={"action": "confirm"},
        headers=_auth(ctx["admin"]),
    )
    assert response.status_code == 200
    assert response.json()["confidence"] == "inferred"
    assert response.json()["review_status"] == "confirmed"


async def test_external_dataset_query_api(client, db_session):
    ctx = await _seed(db_session)
    # _seed already created two external topics; add one relation and one ref.
    db_session.add(
        TaxonomyExternalRelation(
            source_id=ctx["source"].id,
            topic_external_id="cnm_093",
            prerequisite_external_id="cnm_088",
            strength="hard",
            relation_kind="internal",
        )
    )
    db_session.add(
        TaxonomyExternalTopicStandard(
            source_id=ctx["source"].id,
            external_topic_id="cnm_093",
            standard_id="cms-2022:4.NA.01",
            confidence="exact",
        )
    )
    await db_session.commit()

    topics = await client.get(f"{API}/external-topics", headers=_auth(ctx["reviewer"]))
    assert topics.status_code == 200
    assert {row["external_id"] for row in topics.json()} >= {"cnm_093", "cnm_001"}
    relations = await client.get(f"{API}/external-relations", headers=_auth(ctx["reviewer"]))
    assert relations.status_code == 200
    assert relations.json()[0]["relation_kind"] == "internal"
    refs = await client.get(f"{API}/external-standard-links", headers=_auth(ctx["reviewer"]))
    assert refs.status_code == 200
    assert refs.json()[0]["confidence"] == "exact"


async def test_batch_api_preview_execute_rollback(client, db_session):
    ctx = await _seed(db_session)
    preview = await client.post(
        f"{API}/batches/preview",
        json={"source_id": ctx["source"].id},
        headers=_auth(ctx["reviewer"]),
    )
    assert preview.status_code == 200
    assert preview.json()["summary"]["pending_standard_links"] == 1

    created = await client.post(
        f"{API}/batches",
        json={"source_id": ctx["source"].id, "mode": "apply"},
        headers=_auth(ctx["admin"]),
    )
    assert created.status_code == 200, created.text
    batch_id = created.json()["id"]

    executed = await client.post(
        f"{API}/batches/{batch_id}/execute", headers=_auth(ctx["admin"])
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["change_count"] >= 1

    again = await client.post(
        f"{API}/batches/{batch_id}/execute", headers=_auth(ctx["admin"])
    )
    assert again.status_code == 200
    assert again.json()["change_count"] == 0

    rolled = await client.post(
        f"{API}/batches/{batch_id}/rollback", headers=_auth(ctx["admin"])
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["restored_changes"] >= 1
