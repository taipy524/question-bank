"""Stage-3 taxonomy review and batch services.

Only taxonomy tables are written here. Existing knowledge points are read and,
for an *approved* new topic, a new knowledge point is created through the normal
model; existing ids/rows are never rebuilt or deleted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.crud_knowledge_point import knowledge_point as crud_kp
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.taxonomy import (
    KnowledgePointTaxonomy,
    TaxonomyExternalTopic,
    TaxonomyImportBatch,
    TaxonomyImportChange,
    TaxonomyMappingTarget,
    TaxonomyPrerequisite,
    TaxonomyQuestionLinkMigration,
    TaxonomySource,
    TaxonomyStandard,
    TaxonomyTopicMapping,
    TaxonomyTopicStandard,
)

# Kept in sync with reports/10 and reports/12. These pairs require an explicit
# acknowledgement and a comment before confirmation; batch execution never
# confirms a pending mapping on its own.
HIGH_RISK_PAIRS = {
    ("cnm_093", 10),
    ("cnm_200", 19),
    ("cnm_208", 10),
}

MAPPING_TRANSITIONS = {
    "pending_review": {
        "confirmed",
        "rejected",
        "deferred",
        "needs_split",
        "needs_merge",
    },
    "new_topic_pending": {
        "confirmed",
        "rejected",
        "deferred",
        "needs_split",
        "needs_merge",
    },
    "needs_split": {"pending_review", "rejected", "deferred", "confirmed"},
    "needs_merge": {"pending_review", "rejected", "deferred", "confirmed"},
    "deferred": {"pending_review", "rejected", "confirmed"},
    "confirmed": {"pending_review", "deferred"},
    "rejected": {"pending_review"},
}
ACTION_STATUS = {
    "confirm": "confirmed",
    "reject": "rejected",
    "defer": "deferred",
    "split": "needs_split",
    "merge": "needs_merge",
    "new_topic": "new_topic_pending",
    "undo": "pending_review",
    "reopen": "pending_review",
}
# Question-link review actions are independent from ``result``.
QUESTION_LINK_ACTIONS = {
    "approve": "approved",
    "reject": "rejected",
    "defer": "deferred",
    "reopen": "pending_review",
}


class TaxonomyError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _mapping_key(source_id: int, external_id: int, internal_id: int | None) -> str:
    return f"m:{source_id}:{external_id}:{internal_id or 0}"


def _prereq_key(source_id: int, topic_id: int, prerequisite_id: int) -> str:
    return f"p:{source_id}:{topic_id}:{prerequisite_id}"


def _as_dict(row: TaxonomyTopicMapping) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "external_topic_id": row.external_topic_id,
        "internal_knowledge_point_id": row.internal_knowledge_point_id,
        "match_type": row.match_type,
        "confidence": row.confidence,
        "reason": row.reason,
        "conflict": row.conflict,
        "high_risk": row.high_risk,
        "risk": row.risk,
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "batch_id": row.batch_id,
        "revision": row.revision,
        "supersedes_id": row.supersedes_id,
        "is_current": row.is_current,
    }


# ---------------------------------------------------------------------------
# Reference data helpers (used by tests / a future import command)
# ---------------------------------------------------------------------------


async def create_source(
    db: AsyncSession,
    *,
    slug: str,
    repo_url: str,
    commit_sha: str,
    license_status: str = "unconfirmed",
    license_note: str | None = None,
    data_version: str | None = None,
    content_hash: str | None = None,
) -> TaxonomySource:
    source = TaxonomySource(
        slug=slug,
        repo_url=repo_url,
        commit_sha=commit_sha,
        license_status=license_status,
        license_note=license_note,
        data_version=data_version,
        content_hash=content_hash,
        retrieved_at=_now(),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def list_sources(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(TaxonomySource).order_by(TaxonomySource.id))).scalars().all()
    return [
        {
            "id": row.id,
            "slug": row.slug,
            "repo_url": row.repo_url,
            "commit_sha": row.commit_sha,
            "data_version": row.data_version,
            "license_status": row.license_status,
            "status": row.status,
            "content_hash": row.content_hash,
        }
        for row in rows
    ]


async def upsert_external_topic(
    db: AsyncSession,
    *,
    source_id: int,
    external_id: str,
    name: str,
    domain: str | None = None,
    grade: int | None = None,
    semester: str | None = None,
    chapter: str | None = None,
    topic_type: str | None = None,
    mastery_criteria: Any = None,
    raw: Any = None,
    parent_external_id: str | None = None,
) -> TaxonomyExternalTopic:
    result = await db.execute(
        select(TaxonomyExternalTopic).where(
            TaxonomyExternalTopic.source_id == source_id,
            TaxonomyExternalTopic.external_id == external_id,
        )
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        topic = TaxonomyExternalTopic(source_id=source_id, external_id=external_id, name=name)
        db.add(topic)
    topic.name = name
    topic.domain = domain
    topic.grade = grade
    topic.semester = semester
    topic.chapter = chapter
    topic.topic_type = topic_type
    topic.mastery_criteria = mastery_criteria
    topic.raw = raw
    topic.parent_external_id = parent_external_id
    await db.commit()
    await db.refresh(topic)
    return topic


async def upsert_standard(
    db: AsyncSession,
    *,
    source_id: int,
    standard_id: str,
    content: str,
    domain: str | None = None,
    section: str | None = None,
    clause: str | None = None,
    verbatim: bool | None = None,
    text_status: str | None = None,
    default_confidence: str | None = None,
    revision: str | None = None,
) -> TaxonomyStandard:
    result = await db.execute(
        select(TaxonomyStandard).where(
            TaxonomyStandard.source_id == source_id,
            TaxonomyStandard.standard_id == standard_id,
        )
    )
    standard = result.scalar_one_or_none()
    if standard is None:
        standard = TaxonomyStandard(source_id=source_id, standard_id=standard_id, content=content)
        db.add(standard)
    standard.content = content
    standard.domain = domain
    standard.section = section
    standard.clause = clause
    standard.verbatim = verbatim
    standard.text_status = text_status
    standard.default_confidence = default_confidence
    standard.revision = revision
    await db.commit()
    await db.refresh(standard)
    return standard


async def create_mapping(
    db: AsyncSession,
    *,
    source_id: int,
    external_topic_id: int,
    internal_knowledge_point_id: int | None,
    match_type: str = "exact",
    confidence: float | None = None,
    reason: str = "",
    conflict: bool = False,
    high_risk: bool = False,
    risk: str | None = None,
    review_status: str = "pending_review",
    batch_id: int | None = None,
) -> TaxonomyTopicMapping:
    if (match_type == "new_topic") != (internal_knowledge_point_id is None):
        raise TaxonomyError("new_topic rows must have NULL internal id; others must have an id")
    mapping = TaxonomyTopicMapping(
        source_id=source_id,
        external_topic_id=external_topic_id,
        internal_knowledge_point_id=internal_knowledge_point_id,
        match_type=match_type,
        confidence=confidence,
        reason=reason,
        conflict=conflict,
        high_risk=high_risk,
        risk=risk,
        review_status=review_status,
        batch_id=batch_id,
        revision=1,
        is_current=True,
        current_key=_mapping_key(source_id, external_topic_id, internal_knowledge_point_id),
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    return mapping


# ---------------------------------------------------------------------------
# Mapping review
# ---------------------------------------------------------------------------


async def list_mappings(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    review_status: str | None = None,
    match_type: str | None = None,
    high_risk: bool | None = None,
    include_history: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conditions = []
    if not include_history:
        conditions.append(TaxonomyTopicMapping.is_current.is_(True))
    if source_id is not None:
        conditions.append(TaxonomyTopicMapping.source_id == source_id)
    if review_status:
        conditions.append(TaxonomyTopicMapping.review_status == review_status)
    if match_type:
        conditions.append(TaxonomyTopicMapping.match_type == match_type)
    if high_risk is not None:
        conditions.append(TaxonomyTopicMapping.high_risk.is_(high_risk))

    statement = (
        select(TaxonomyTopicMapping, TaxonomyExternalTopic, KnowledgePoint)
        .join(
            TaxonomyExternalTopic,
            and_(
                TaxonomyExternalTopic.id == TaxonomyTopicMapping.external_topic_id,
                TaxonomyExternalTopic.source_id == TaxonomyTopicMapping.source_id,
            ),
        )
        .outerjoin(
            KnowledgePoint,
            KnowledgePoint.id == TaxonomyTopicMapping.internal_knowledge_point_id,
        )
        .where(*conditions)
        .order_by(TaxonomyTopicMapping.external_topic_id, TaxonomyTopicMapping.revision.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(statement)).all()
    return [
        {
            **_as_dict(mapping),
            "external": {
                "id": topic.id,
                "external_id": topic.external_id,
                "name": topic.name,
                "domain": topic.domain,
                "grade": topic.grade,
                "semester": topic.semester,
                "chapter": topic.chapter,
            },
            "internal": (
                {
                    "id": internal.id,
                    "name": internal.name,
                    "parent_id": internal.parent_id,
                    "subject_id": internal.subject_id,
                }
                if internal is not None
                else None
            ),
        }
        for mapping, topic, internal in rows
    ]


async def get_mapping(db: AsyncSession, mapping_id: int, *, current_only: bool = True) -> TaxonomyTopicMapping:
    statement = select(TaxonomyTopicMapping).where(TaxonomyTopicMapping.id == mapping_id)
    if current_only:
        statement = statement.where(TaxonomyTopicMapping.is_current.is_(True))
    mapping = (await db.execute(statement)).scalar_one_or_none()
    if mapping is None:
        raise TaxonomyError("mapping not found", status_code=404)
    return mapping


async def review_mapping(
    db: AsyncSession,
    *,
    mapping_id: int,
    action: str,
    reviewer_id: int | None,
    comment: str = "",
    acknowledge_high_risk: bool = False,
) -> dict[str, Any]:
    mapping = await get_mapping(db, mapping_id)
    target = ACTION_STATUS.get(action)
    if target is None:
        raise TaxonomyError(f"unknown action: {action}")
    if target not in MAPPING_TRANSITIONS.get(mapping.review_status, set()):
        raise TaxonomyError(
            f"invalid transition: {mapping.review_status} -> {target}", status_code=409
        )
    if action == "confirm" and mapping.match_type == "new_topic":
        raise TaxonomyError(
            "new topics must be approved via the new-topic approval flow", status_code=409
        )

    external = await db.get(TaxonomyExternalTopic, mapping.external_topic_id)
    high_risk = mapping.high_risk or (
        external is not None
        and (external.external_id, mapping.internal_knowledge_point_id) in HIGH_RISK_PAIRS
    )
    if high_risk and action == "confirm":
        if not acknowledge_high_risk:
            raise TaxonomyError("high-risk candidate requires explicit acknowledgement")
        if not comment.strip():
            raise TaxonomyError("high-risk confirmation requires a comment")

    mapping.is_current = False
    mapping.current_key = None
    await db.flush()

    new_row = TaxonomyTopicMapping(
        source_id=mapping.source_id,
        external_topic_id=mapping.external_topic_id,
        internal_knowledge_point_id=mapping.internal_knowledge_point_id,
        match_type=mapping.match_type,
        confidence=mapping.confidence,
        reason=mapping.reason,
        conflict=mapping.conflict,
        high_risk=high_risk,
        risk=mapping.risk,
        review_status=target,
        reviewed_by=reviewer_id,
        reviewed_at=_now(),
        batch_id=mapping.batch_id,
        revision=mapping.revision + 1,
        supersedes_id=mapping.id,
        is_current=True,
        current_key=_mapping_key(
            mapping.source_id, mapping.external_topic_id, mapping.internal_knowledge_point_id
        ),
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)
    if target != "confirmed":
        stale = await _mark_dependents_stale(
            db,
            mapping_id=mapping.id,
            reason=f"mapping review status changed to {target}",
        )
        if stale:
            await db.commit()
    return _as_dict(new_row)


async def mapping_history(
    db: AsyncSession,
    *,
    source_id: int,
    external_topic_id: int,
    internal_knowledge_point_id: int | None,
) -> list[dict[str, Any]]:
    conditions = [
        TaxonomyTopicMapping.source_id == source_id,
        TaxonomyTopicMapping.external_topic_id == external_topic_id,
    ]
    if internal_knowledge_point_id is None:
        conditions.append(TaxonomyTopicMapping.internal_knowledge_point_id.is_(None))
    else:
        conditions.append(
            TaxonomyTopicMapping.internal_knowledge_point_id == internal_knowledge_point_id
        )
    rows = (
        await db.execute(
            select(TaxonomyTopicMapping)
            .where(*conditions)
            .order_by(TaxonomyTopicMapping.revision.asc())
        )
    ).scalars().all()
    return [_as_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# New-topic review
# ---------------------------------------------------------------------------


async def list_new_topics(
    db: AsyncSession, *, source_id: int | None = None, skip: int = 0, limit: int = 100
) -> list[dict[str, Any]]:
    return await list_mappings(
        db,
        source_id=source_id,
        review_status="new_topic_pending",
        match_type="new_topic",
        skip=skip,
        limit=limit,
    )


async def approve_new_topic(
    db: AsyncSession,
    *,
    mapping_id: int,
    reviewer_id: int | None,
    subject_id: int,
    parent_id: int | None,
    name: str | None = None,
    comment: str = "",
) -> dict[str, Any]:
    mapping = await get_mapping(db, mapping_id)
    if mapping.match_type != "new_topic" or mapping.review_status != "new_topic_pending":
        raise TaxonomyError("mapping is not a pending new topic", status_code=409)
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise TaxonomyError("subject not found", status_code=404)
    if parent_id is not None:
        parent = await db.get(KnowledgePoint, parent_id)
        if parent is None or parent.subject_id != subject_id:
            raise TaxonomyError("parent knowledge point is invalid for this subject")

    external = await db.get(TaxonomyExternalTopic, mapping.external_topic_id)
    if external is None:
        raise TaxonomyError("external topic not found", status_code=404)
    topic_name = (name or external.name).strip()
    if not topic_name:
        raise TaxonomyError("new knowledge point name is empty")

    duplicate = await db.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.subject_id == subject_id,
            func.lower(KnowledgePoint.name) == topic_name.lower(),
        )
    )
    if duplicate.scalars().first() is not None:
        raise TaxonomyError("a knowledge point with the same name already exists", status_code=409)

    slug = await crud_kp.make_unique_slug(db, subject_id, topic_name)
    knowledge_point = KnowledgePoint(
        name=topic_name,
        slug=slug,
        subject_id=subject_id,
        parent_id=parent_id,
        created_by=reviewer_id,
        updated_by=reviewer_id,
    )
    db.add(knowledge_point)
    await db.flush()
    db.add(
        KnowledgePointTaxonomy(
            knowledge_point_id=knowledge_point.id,
            source_id=mapping.source_id,
            external_topic_id=mapping.external_topic_id,
            stage="初中" if external.grade in (7, 8, 9) else None,
            grade=external.grade,
            semester=external.semester,
            chapter=external.chapter,
            domain=external.domain,
            is_legacy=False,
            is_active=True,
        )
    )

    mapping.is_current = False
    mapping.current_key = None
    await db.flush()
    new_row = TaxonomyTopicMapping(
        source_id=mapping.source_id,
        external_topic_id=mapping.external_topic_id,
        internal_knowledge_point_id=knowledge_point.id,
        match_type="exact",
        confidence=1.0,
        reason=(comment or "approved new topic"),
        review_status="confirmed",
        reviewed_by=reviewer_id,
        reviewed_at=_now(),
        revision=mapping.revision + 1,
        supersedes_id=mapping.id,
        is_current=True,
        current_key=_mapping_key(mapping.source_id, mapping.external_topic_id, knowledge_point.id),
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)
    await db.refresh(knowledge_point)
    return {
        "mapping": _as_dict(new_row),
        "knowledge_point": {
            "id": knowledge_point.id,
            "name": knowledge_point.name,
            "slug": knowledge_point.slug,
            "parent_id": knowledge_point.parent_id,
            "subject_id": knowledge_point.subject_id,
        },
    }


async def reject_new_topic(
    db: AsyncSession, *, mapping_id: int, reviewer_id: int | None, comment: str = ""
) -> dict[str, Any]:
    return await review_mapping(
        db,
        mapping_id=mapping_id,
        action="reject",
        reviewer_id=reviewer_id,
        comment=comment,
    )


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def _edge_cycle(
    edges: Iterable[tuple[int, int]], new_edge: tuple[int, int]
) -> list[int] | None:
    adjacency: dict[int, list[int]] = {}
    for topic, prerequisite in list(edges) + [new_edge]:
        adjacency.setdefault(topic, []).append(prerequisite)
    # Does prerequisite reach topic already? Then adding topic->prerequisite cycles.
    target, start = new_edge
    stack = [start]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return [target, start]
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return None


async def list_prerequisites(
    db: AsyncSession, *, source_id: int | None = None, current_only: bool = True
) -> list[dict[str, Any]]:
    conditions = []
    if current_only:
        conditions.append(TaxonomyPrerequisite.is_current.is_(True))
    if source_id is not None:
        conditions.append(TaxonomyPrerequisite.source_id == source_id)
    rows = (
        await db.execute(
            select(TaxonomyPrerequisite)
            .where(*conditions)
            .order_by(TaxonomyPrerequisite.knowledge_point_id, TaxonomyPrerequisite.id)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "knowledge_point_id": row.knowledge_point_id,
            "prerequisite_knowledge_point_id": row.prerequisite_knowledge_point_id,
            "external_topic_id": row.external_topic_id,
            "external_prerequisite_id": row.external_prerequisite_id,
            "strength": row.strength,
            "review_status": row.review_status,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "revision": row.revision,
            "is_current": row.is_current,
        }
        for row in rows
    ]


async def review_prerequisite(
    db: AsyncSession,
    *,
    prerequisite_id: int,
    action: str,
    reviewer_id: int | None,
    comment: str = "",
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(TaxonomyPrerequisite).where(
                TaxonomyPrerequisite.id == prerequisite_id,
                TaxonomyPrerequisite.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise TaxonomyError("prerequisite not found", status_code=404)
    if action not in {"confirm", "reject", "undo"}:
        raise TaxonomyError(f"unknown action: {action}")
    target = {"confirm": "confirmed", "reject": "rejected", "undo": "pending_review"}[action]
    allowed = {
        "pending_review": {"confirmed", "rejected"},
        "confirmed": {"pending_review"},
        "rejected": {"pending_review"},
    }
    if target not in allowed.get(row.review_status, set()):
        raise TaxonomyError(
            f"invalid transition: {row.review_status} -> {target}", status_code=409
        )
    if row.knowledge_point_id == row.prerequisite_knowledge_point_id:
        raise TaxonomyError("self-loop prerequisite is not allowed", status_code=409)

    if action == "confirm":
        duplicate = (
            await db.execute(
                select(TaxonomyPrerequisite).where(
                    TaxonomyPrerequisite.source_id == row.source_id,
                    TaxonomyPrerequisite.knowledge_point_id == row.knowledge_point_id,
                    TaxonomyPrerequisite.prerequisite_knowledge_point_id
                    == row.prerequisite_knowledge_point_id,
                    TaxonomyPrerequisite.review_status == "confirmed",
                    TaxonomyPrerequisite.is_current.is_(True),
                    TaxonomyPrerequisite.id != row.id,
                )
            )
        ).scalars().first()
        if duplicate is not None:
            raise TaxonomyError("duplicate confirmed prerequisite", status_code=409)
        existing = (
            await db.execute(
                select(TaxonomyPrerequisite).where(
                    TaxonomyPrerequisite.source_id == row.source_id,
                    TaxonomyPrerequisite.review_status == "confirmed",
                    TaxonomyPrerequisite.is_current.is_(True),
                    TaxonomyPrerequisite.id != row.id,
                )
            )
        ).scalars().all()
        cycle = _edge_cycle(
            [(item.knowledge_point_id, item.prerequisite_knowledge_point_id) for item in existing],
            (row.knowledge_point_id, row.prerequisite_knowledge_point_id),
        )
        if cycle:
            raise TaxonomyError("prerequisite cycle detected", status_code=409, details=cycle)

    row.is_current = False
    row.current_key = None
    await db.flush()
    new_row = TaxonomyPrerequisite(
        source_id=row.source_id,
        knowledge_point_id=row.knowledge_point_id,
        prerequisite_knowledge_point_id=row.prerequisite_knowledge_point_id,
        external_topic_id=row.external_topic_id,
        external_prerequisite_id=row.external_prerequisite_id,
        strength=row.strength,
        raw_evidence=row.raw_evidence,
        review_status=target,
        reviewed_by=reviewer_id,
        reviewed_at=_now(),
        batch_id=row.batch_id,
        revision=row.revision + 1,
        supersedes_id=row.id,
        is_current=True,
        current_key=_prereq_key(
            row.source_id, row.knowledge_point_id, row.prerequisite_knowledge_point_id
        ),
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)
    return {
        "id": new_row.id,
        "knowledge_point_id": new_row.knowledge_point_id,
        "prerequisite_knowledge_point_id": new_row.prerequisite_knowledge_point_id,
        "strength": new_row.strength,
        "review_status": new_row.review_status,
        "reviewed_by": new_row.reviewed_by,
        "reviewed_at": new_row.reviewed_at.isoformat() if new_row.reviewed_at else None,
        "revision": new_row.revision,
    }


async def prerequisite_conflicts(db: AsyncSession, *, source_id: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(TaxonomyPrerequisite).where(
                TaxonomyPrerequisite.source_id == source_id,
                TaxonomyPrerequisite.is_current.is_(True),
            )
        )
    ).scalars().all()
    conflicts: list[dict[str, Any]] = []
    seen: dict[tuple[int, int], int] = {}
    for row in rows:
        if row.knowledge_point_id == row.prerequisite_knowledge_point_id:
            conflicts.append({"type": "self_loop", "prerequisite_id": row.id})
        key = (row.knowledge_point_id, row.prerequisite_knowledge_point_id)
        if key in seen:
            conflicts.append({"type": "duplicate", "prerequisite_id": row.id, "duplicate_of": seen[key]})
        else:
            seen[key] = row.id
    confirmed = [
        (row.knowledge_point_id, row.prerequisite_knowledge_point_id)
        for row in rows
        if row.review_status in {"pending_review", "confirmed"}
    ]
    for topic, prerequisite in confirmed:
        cycle = _edge_cycle([edge for edge in confirmed if edge != (topic, prerequisite)], (topic, prerequisite))
        if cycle:
            conflicts.append({"type": "cycle", "edge": [topic, prerequisite], "path": cycle})
    return conflicts


# ---------------------------------------------------------------------------
# Standards
# ---------------------------------------------------------------------------


async def list_standards(
    db: AsyncSession, *, source_id: int | None = None, skip: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    conditions = []
    if source_id is not None:
        conditions.append(TaxonomyStandard.source_id == source_id)
    rows = (
        await db.execute(
            select(TaxonomyStandard)
            .where(*conditions)
            .order_by(TaxonomyStandard.standard_id)
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "standard_id": row.standard_id,
            "domain": row.domain,
            "section": row.section,
            "clause": row.clause,
            "content": row.content,
            "page_or_ref": row.page_or_ref,
            "verbatim": row.verbatim,
            "text_status": row.text_status,
            "default_confidence": row.default_confidence,
            "revision": row.revision,
            "is_active": row.is_active,
        }
        for row in rows
    ]


async def list_topic_standards(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    review_status: str | None = None,
    current_only: bool = True,
) -> list[dict[str, Any]]:
    conditions = []
    if current_only:
        conditions.append(TaxonomyTopicStandard.is_current.is_(True))
    if source_id is not None:
        conditions.append(TaxonomyTopicStandard.source_id == source_id)
    if review_status:
        conditions.append(TaxonomyTopicStandard.review_status == review_status)
    rows = (
        await db.execute(
            select(TaxonomyTopicStandard)
            .where(*conditions)
            .order_by(TaxonomyTopicStandard.knowledge_point_id, TaxonomyTopicStandard.id)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "knowledge_point_id": row.knowledge_point_id,
            "standard_id": row.standard_id,
            "confidence": row.confidence,
            "review_status": row.review_status,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "revision": row.revision,
            "is_current": row.is_current,
            "batch_id": row.batch_id,
        }
        for row in rows
    ]


async def review_topic_standard(
    db: AsyncSession, *, link_id: int, action: str, reviewer_id: int | None, comment: str = ""
) -> dict[str, Any]:
    link = (
        await db.execute(
            select(TaxonomyTopicStandard).where(
                TaxonomyTopicStandard.id == link_id,
                TaxonomyTopicStandard.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise TaxonomyError("standard link not found", status_code=404)
    if action not in {"confirm", "reject", "undo"}:
        raise TaxonomyError(f"unknown action: {action}")
    target = {"confirm": "confirmed", "reject": "rejected", "undo": "pending_review"}[action]
    allowed = {
        "pending_review": {"confirmed", "rejected"},
        "confirmed": {"pending_review"},
        "rejected": {"pending_review"},
    }
    if target not in allowed.get(link.review_status, set()):
        raise TaxonomyError(f"invalid transition: {link.review_status} -> {target}", status_code=409)

    link.is_current = False
    link.current_key = None
    await db.flush()
    new_row = TaxonomyTopicStandard(
        source_id=link.source_id,
        knowledge_point_id=link.knowledge_point_id,
        standard_id=link.standard_id,
        confidence=link.confidence,
        review_status=target,
        reviewed_by=reviewer_id,
        reviewed_at=_now(),
        batch_id=link.batch_id,
        revision=link.revision + 1,
        supersedes_id=link.id,
        is_current=True,
        current_key=f"s:{link.source_id}:{link.knowledge_point_id}:{link.standard_id}",
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)
    return {
        "id": new_row.id,
        "knowledge_point_id": new_row.knowledge_point_id,
        "standard_id": new_row.standard_id,
        "confidence": new_row.confidence,
        "review_status": new_row.review_status,
        "reviewed_by": new_row.reviewed_by,
        "reviewed_at": new_row.reviewed_at.isoformat() if new_row.reviewed_at else None,
        "revision": new_row.revision,
    }


# ---------------------------------------------------------------------------
# Import batches (materialise pending prerequisites/standard links)
# ---------------------------------------------------------------------------


async def _pending_counts(db: AsyncSession, source_id: int) -> dict[str, int]:
    prereq = (
        await db.execute(
            select(func.count(TaxonomyPrerequisite.id)).where(
                TaxonomyPrerequisite.source_id == source_id,
                TaxonomyPrerequisite.review_status == "pending_review",
                TaxonomyPrerequisite.is_current.is_(True),
            )
        )
    ).scalar_one()
    standards = (
        await db.execute(
            select(func.count(TaxonomyTopicStandard.id)).where(
                TaxonomyTopicStandard.source_id == source_id,
                TaxonomyTopicStandard.review_status == "pending_review",
                TaxonomyTopicStandard.is_current.is_(True),
            )
        )
    ).scalar_one()
    mappings = (
        await db.execute(
            select(func.count(TaxonomyTopicMapping.id)).where(
                TaxonomyTopicMapping.source_id == source_id,
                TaxonomyTopicMapping.review_status.in_(["confirmed", "pending_review"]),
                TaxonomyTopicMapping.is_current.is_(True),
            )
        )
    ).scalar_one()
    new_topics = (
        await db.execute(
            select(func.count(TaxonomyTopicMapping.id)).where(
                TaxonomyTopicMapping.source_id == source_id,
                TaxonomyTopicMapping.review_status == "new_topic_pending",
                TaxonomyTopicMapping.is_current.is_(True),
            )
        )
    ).scalar_one()
    return {
        "pending_prerequisites": int(prereq),
        "pending_standard_links": int(standards),
        "current_mappings": int(mappings),
        "pending_new_topics": int(new_topics),
    }


async def preview_batch(db: AsyncSession, *, source_id: int) -> dict[str, Any]:
    source = await db.get(TaxonomySource, source_id)
    if source is None:
        raise TaxonomyError("source not found", status_code=404)
    counts = await _pending_counts(db, source_id)
    conflicts = await prerequisite_conflicts(db, source_id=source_id)
    high_risk = (
        await db.execute(
            select(func.count(TaxonomyTopicMapping.id)).where(
                TaxonomyTopicMapping.source_id == source_id,
                TaxonomyTopicMapping.high_risk.is_(True),
                TaxonomyTopicMapping.is_current.is_(True),
            )
        )
    ).scalar_one()
    return {
        "source_id": source_id,
        "summary": {
            **counts,
            "high_risk_mappings": int(high_risk),
            "prerequisite_conflicts": len(conflicts),
        },
        "conflicts": conflicts,
    }


async def create_batch(
    db: AsyncSession,
    *,
    source_id: int,
    mode: str,
    user_id: int | None,
    notes: str | None = None,
) -> TaxonomyImportBatch:
    if mode not in {"dry_run", "apply"}:
        raise TaxonomyError("invalid batch mode")
    preview = await preview_batch(db, source_id=source_id)
    batch = TaxonomyImportBatch(
        source_id=source_id,
        mode=mode,
        status="validated",
        summary=preview["summary"],
        conflicts=preview["conflicts"],
        created_by=user_id,
        notes=notes,
        started_at=_now() if mode == "apply" else None,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def execute_batch(
    db: AsyncSession, *, batch_id: int, user_id: int | None = None
) -> dict[str, Any]:
    batch = await db.get(TaxonomyImportBatch, batch_id)
    if batch is None:
        raise TaxonomyError("batch not found", status_code=404)
    if batch.status == "applied":
        # Idempotent re-execution: nothing pending, no new changes.
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "change_count": 0,
            "summary": batch.summary,
        }
    if batch.status not in {"validated", "draft"}:
        raise TaxonomyError(f"batch cannot be executed from {batch.status}", status_code=409)
    if batch.mode != "apply":
        raise TaxonomyError("dry-run batches cannot be executed", status_code=409)
    conflicts = await prerequisite_conflicts(db, source_id=batch.source_id)
    if conflicts:
        raise TaxonomyError(
            "prerequisite conflicts must be reviewed before execution",
            status_code=409,
            details=conflicts,
        )

    changes: list[TaxonomyImportChange] = []
    prereqs = (
        await db.execute(
            select(TaxonomyPrerequisite).where(
                TaxonomyPrerequisite.source_id == batch.source_id,
                TaxonomyPrerequisite.review_status == "pending_review",
                TaxonomyPrerequisite.is_current.is_(True),
            )
        )
    ).scalars().all()
    for row in prereqs:
        before = {
            "id": row.id,
            "review_status": row.review_status,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        }
        row.review_status = "confirmed"
        row.reviewed_by = user_id
        row.reviewed_at = _now()
        changes.append(
            TaxonomyImportChange(
                batch_id=batch.id,
                entity_type="knowledge_point_prerequisite",
                entity_pk=str(row.id),
                operation="update",
                before_json=before,
                after_json={
                    "id": row.id,
                    "review_status": "confirmed",
                    "reviewed_by": row.reviewed_by,
                    "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                },
            )
        )

    links = (
        await db.execute(
            select(TaxonomyTopicStandard).where(
                TaxonomyTopicStandard.source_id == batch.source_id,
                TaxonomyTopicStandard.review_status == "pending_review",
                TaxonomyTopicStandard.is_current.is_(True),
            )
        )
    ).scalars().all()
    for row in links:
        before = {
            "id": row.id,
            "review_status": row.review_status,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        }
        row.review_status = "confirmed"
        row.reviewed_by = user_id
        row.reviewed_at = _now()
        changes.append(
            TaxonomyImportChange(
                batch_id=batch.id,
                entity_type="knowledge_point_standard",
                entity_pk=str(row.id),
                operation="update",
                before_json=before,
                after_json={
                    "id": row.id,
                    "review_status": "confirmed",
                    "reviewed_by": row.reviewed_by,
                    "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                },
            )
        )

    for change in changes:
        db.add(change)
    batch.status = "applied"
    batch.finished_at = _now()
    batch.summary = {
        **(batch.summary or {}),
        "applied_prerequisites": len(prereqs),
        "applied_standard_links": len(links),
    }
    try:
        await db.commit()
    except Exception:
        # Nothing from this batch is committed; the caller sees the failure and
        # the session is rolled back.  This keeps mid-execution failures atomic.
        await db.rollback()
        raise
    await db.refresh(batch)
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "change_count": len(changes),
        "summary": batch.summary,
    }


async def rollback_batch(
    db: AsyncSession, *, batch_id: int, user_id: int | None = None
) -> dict[str, Any]:
    batch = await db.get(TaxonomyImportBatch, batch_id)
    if batch is None:
        raise TaxonomyError("batch not found", status_code=404)
    if batch.status != "applied":
        raise TaxonomyError(f"batch cannot be rolled back from {batch.status}", status_code=409)
    changes = (
        await db.execute(
            select(TaxonomyImportChange)
            .where(TaxonomyImportChange.batch_id == batch_id)
            .order_by(TaxonomyImportChange.id.desc())
        )
    ).scalars().all()
    for change in changes:
        before = change.before_json or {}
        reviewed_at = _parse_datetime(before.get("reviewed_at"))
        if change.entity_type == "knowledge_point_prerequisite":
            row = await db.get(TaxonomyPrerequisite, int(change.entity_pk))
            if row is not None:
                row.review_status = before.get("review_status", "pending_review")
                row.reviewed_by = before.get("reviewed_by")
                row.reviewed_at = reviewed_at
        elif change.entity_type == "knowledge_point_standard":
            row = await db.get(TaxonomyTopicStandard, int(change.entity_pk))
            if row is not None:
                row.review_status = before.get("review_status", "pending_review")
                row.reviewed_by = before.get("reviewed_by")
                row.reviewed_at = reviewed_at
    batch.status = "rolled_back"
    batch.finished_at = _now()
    rollback_batch_row = TaxonomyImportBatch(
        source_id=batch.source_id,
        mode="apply",
        status="rolled_back",
        summary={"rollback_of": batch.id, "restored_changes": len(changes)},
        rollback_of_batch_id=batch.id,
        created_by=user_id,
    )
    db.add(rollback_batch_row)
    await db.commit()
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "restored_changes": len(changes),
        "rollback_batch_id": rollback_batch_row.id,
    }


async def list_batches(
    db: AsyncSession, *, source_id: int | None = None, skip: int = 0, limit: int = 50
) -> list[dict[str, Any]]:
    conditions = []
    if source_id is not None:
        conditions.append(TaxonomyImportBatch.source_id == source_id)
    rows = (
        await db.execute(
            select(TaxonomyImportBatch)
            .where(*conditions)
            .order_by(TaxonomyImportBatch.id.desc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "mode": row.mode,
            "status": row.status,
            "summary": row.summary,
            "conflicts": row.conflicts,
            "created_by": row.created_by,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "rollback_of_batch_id": row.rollback_of_batch_id,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Review workflow: deferred / reassign / one-to-many / question links
# ---------------------------------------------------------------------------


def _as_target(row: TaxonomyMappingTarget) -> dict[str, Any]:
    return {
        "id": row.id,
        "mapping_id": row.mapping_id,
        "knowledge_point_id": row.knowledge_point_id,
        "is_primary": bool(row.is_primary),
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_comment": row.review_comment,
    }


def _as_link(row: TaxonomyQuestionLinkMigration) -> dict[str, Any]:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "question_id": row.question_id,
        "legacy_knowledge_point_id": row.legacy_knowledge_point_id,
        "new_knowledge_point_id": row.new_knowledge_point_id,
        "result": row.result,
        "reason": row.reason,
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_comment": row.review_comment,
        "depends_on_mapping_id": row.depends_on_mapping_id,
    }


async def _mark_dependents_stale(db: AsyncSession, *, mapping_id: int, reason: str) -> int:
    """Mark question links that depend on a mapping as stale (never delete)."""
    rows = (
        await db.execute(
            select(TaxonomyQuestionLinkMigration).where(
                TaxonomyQuestionLinkMigration.depends_on_mapping_id == mapping_id,
                TaxonomyQuestionLinkMigration.review_status != "stale",
            )
        )
    ).scalars().all()
    for row in rows:
        row.review_status = "stale"
        row.review_comment = reason
        row.updated_at = _now()
    return len(rows)


async def reassign_mapping(
    db: AsyncSession,
    *,
    mapping_id: int,
    internal_knowledge_point_id: int,
    reviewer_id: int | None,
    comment: str = "",
) -> dict[str, Any]:
    """Replace the candidate knowledge point, creating a new revision."""
    mapping = await get_mapping(db, mapping_id)
    if mapping.match_type == "new_topic":
        raise TaxonomyError(
            "new_topic mappings must be resolved via new-topic approval",
            status_code=409,
        )
    knowledge_point = await db.get(KnowledgePoint, internal_knowledge_point_id)
    if knowledge_point is None:
        raise TaxonomyError("knowledge point not found", status_code=404)

    previous_id = mapping.internal_knowledge_point_id
    mapping.is_current = False
    mapping.current_key = None
    await db.flush()

    new_row = TaxonomyTopicMapping(
        source_id=mapping.source_id,
        external_topic_id=mapping.external_topic_id,
        internal_knowledge_point_id=internal_knowledge_point_id,
        match_type="manual",
        confidence=1.0,
        reason=comment or "candidate reassigned",
        conflict=False,
        high_risk=False,
        risk=None,
        review_status="pending_review",
        reviewed_by=reviewer_id,
        reviewed_at=_now(),
        batch_id=mapping.batch_id,
        revision=mapping.revision + 1,
        supersedes_id=mapping.id,
        is_current=True,
        current_key=_mapping_key(
            mapping.source_id, mapping.external_topic_id, internal_knowledge_point_id
        ),
    )
    db.add(new_row)
    await db.flush()
    stale = await _mark_dependents_stale(
        db,
        mapping_id=mapping.id,
        reason=f"mapping reassigned {previous_id} -> {internal_knowledge_point_id}",
    )
    await db.commit()
    await db.refresh(new_row)
    return {
        "mapping": _as_dict(new_row),
        "previous_internal_id": previous_id,
        "new_internal_id": internal_knowledge_point_id,
        "stale_links": stale,
    }


async def set_mapping_targets(
    db: AsyncSession,
    *,
    mapping_id: int,
    knowledge_point_ids: list[int],
    reviewer_id: int | None,
    comment: str = "",
) -> dict[str, Any]:
    """Define one-to-many targets on a new mapping revision."""
    mapping = await get_mapping(db, mapping_id)
    if mapping.match_type == "new_topic":
        raise TaxonomyError(
            "new_topic mappings cannot use one-to-many targets", status_code=409
        )
    ids = list(dict.fromkeys(int(i) for i in knowledge_point_ids))
    if len(ids) < 2:
        raise TaxonomyError("one-to-many targets require at least two knowledge points")
    subject_ids = set()
    for kp_id in ids:
        kp = await db.get(KnowledgePoint, kp_id)
        if kp is None:
            raise TaxonomyError(f"knowledge point {kp_id} not found", status_code=404)
        subject_ids.add(kp.subject_id)
    if len(subject_ids) != 1:
        raise TaxonomyError("one-to-many targets must belong to the same subject")

    primary_id = ids[0]
    mapping.is_current = False
    mapping.current_key = None
    await db.flush()

    new_row = TaxonomyTopicMapping(
        source_id=mapping.source_id,
        external_topic_id=mapping.external_topic_id,
        internal_knowledge_point_id=primary_id,
        match_type="one_to_many",
        confidence=None,
        reason=comment or "one-to-many targets defined",
        conflict=False,
        high_risk=mapping.high_risk,
        risk=mapping.risk,
        review_status="pending_review",
        reviewed_by=reviewer_id,
        reviewed_at=_now(),
        batch_id=mapping.batch_id,
        revision=mapping.revision + 1,
        supersedes_id=mapping.id,
        is_current=True,
        current_key=_mapping_key(mapping.source_id, mapping.external_topic_id, primary_id),
    )
    db.add(new_row)
    await db.flush()

    for index, kp_id in enumerate(ids):
        db.add(
            TaxonomyMappingTarget(
                mapping_id=new_row.id,
                knowledge_point_id=kp_id,
                is_primary=(index == 0),
                review_status="pending_review",
                review_comment=comment,
            )
        )
    stale = await _mark_dependents_stale(
        db, mapping_id=mapping.id, reason="mapping moved to one-to-many"
    )
    await db.commit()
    await db.refresh(new_row)
    targets = (
        await db.execute(
            select(TaxonomyMappingTarget)
            .where(TaxonomyMappingTarget.mapping_id == new_row.id)
            .order_by(TaxonomyMappingTarget.id)
        )
    ).scalars().all()
    return {
        "mapping": _as_dict(new_row),
        "targets": [_as_target(t) for t in targets],
        "stale_links": stale,
    }


async def confirm_mapping_targets(
    db: AsyncSession,
    *,
    mapping_id: int,
    reviewer_id: int | None,
    comment: str = "",
) -> dict[str, Any]:
    """Approve every active target and confirm the one-to-many mapping."""
    mapping = await get_mapping(db, mapping_id)
    if mapping.match_type != "one_to_many":
        raise TaxonomyError("mapping is not one_to_many", status_code=409)
    if not comment.strip():
        raise TaxonomyError(
            "confirming one-to-many targets requires a comment", status_code=409
        )
    targets = (
        await db.execute(
            select(TaxonomyMappingTarget).where(
                TaxonomyMappingTarget.mapping_id == mapping.id,
                TaxonomyMappingTarget.review_status != "rejected",
            )
        )
    ).scalars().all()
    if len(targets) < 2:
        raise TaxonomyError(
            "one-to-many mapping requires at least two active targets", status_code=409
        )
    for target in targets:
        target.review_status = "approved"
        target.reviewed_by = reviewer_id
        target.reviewed_at = _now()
        target.review_comment = comment
    mapping.review_status = "confirmed"
    mapping.reviewed_by = reviewer_id
    mapping.reviewed_at = _now()
    await db.commit()
    return {
        "mapping_id": mapping.id,
        "status": mapping.review_status,
        "approved_targets": len(targets),
        "targets": [_as_target(t) for t in targets],
    }


async def list_question_links(
    db: AsyncSession,
    *,
    review_status: str | None = None,
    result: str | None = None,
    question_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conditions = []
    if review_status:
        conditions.append(TaxonomyQuestionLinkMigration.review_status == review_status)
    if result:
        conditions.append(TaxonomyQuestionLinkMigration.result == result)
    if question_id is not None:
        conditions.append(TaxonomyQuestionLinkMigration.question_id == question_id)
    rows = (
        await db.execute(
            select(TaxonomyQuestionLinkMigration)
            .where(*conditions)
            .order_by(
                TaxonomyQuestionLinkMigration.question_id,
                TaxonomyQuestionLinkMigration.legacy_knowledge_point_id,
            )
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [_as_link(row) for row in rows]


async def get_question_link(db: AsyncSession, link_id: int) -> dict[str, Any]:
    row = await db.get(TaxonomyQuestionLinkMigration, link_id)
    if row is None:
        raise TaxonomyError("question link not found", status_code=404)
    return _as_link(row)


async def review_question_link(
    db: AsyncSession,
    *,
    link_id: int,
    action: str,
    reviewer_id: int | None,
    comment: str = "",
    new_knowledge_point_id: int | None = None,
) -> dict[str, Any]:
    row = await db.get(TaxonomyQuestionLinkMigration, link_id)
    if row is None:
        raise TaxonomyError("question link not found", status_code=404)
    target = QUESTION_LINK_ACTIONS.get(action)
    if target is None:
        raise TaxonomyError(f"unknown action: {action}")
    if new_knowledge_point_id is not None:
        kp = await db.get(KnowledgePoint, new_knowledge_point_id)
        if kp is None:
            raise TaxonomyError("knowledge point not found", status_code=404)
        row.new_knowledge_point_id = new_knowledge_point_id
    if action == "approve" and row.new_knowledge_point_id is None and not comment.strip():
        raise TaxonomyError(
            "approving a link without a target requires a comment", status_code=409
        )
    row.review_status = target
    row.reviewed_by = reviewer_id
    row.reviewed_at = _now()
    row.review_comment = comment
    await db.commit()
    await db.refresh(row)
    return _as_link(row)
