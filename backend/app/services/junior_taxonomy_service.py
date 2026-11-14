"""Simplified junior-high math taxonomy materialization.

This service turns the reviewed external package into QuestionBank's *formal*
knowledge points:

* 315 ``knowledge_points`` rows (QuestionBank auto-increment ids, flat)
* 315 ``knowledge_point_taxonomy`` metadata rows (grade/semester/chapter/domain)
* 563 ``taxonomy_prerequisites`` rows (hard/soft)
* 157 ``taxonomy_standards`` rows
* 383 ``taxonomy_topic_standards`` rows (exact/inferred)

It deliberately does **not** build a review workflow, does not import the 45
primary-to-junior edges, and does not import external practice questions.
Every write is attributed to a ``taxonomy_import_batches`` row so the batch can
be rolled back as a unit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.subject import Subject
from app.models.taxonomy import (
    KnowledgePointTaxonomy,
    TaxonomyImportBatch,
    TaxonomyImportChange,
    TaxonomyPrerequisite,
    TaxonomySource,
    TaxonomyStandard,
    TaxonomyTopicStandard,
)
from app.services import taxonomy_source_import

SOURCE_SLUG = "cn-math-taxonomy"
SOURCE_REPO = "https://github.com/xiaoyang111222/cn-math-taxonomy"
SOURCE_COMMIT = "cf73951"
SOURCE_LICENSE = "CC BY-NC 4.0"
EXPECTED = {
    "topics": 315,
    "internal_edges": 563,
    "standards": 157,
    "topic_standards": 383,
    "cross_stage_edges": 0,
}
STAGE = "初中"


class JuniorImportError(ValueError):
    """Raised when the package or the target database is not importable."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(external_id: str) -> str:
    return external_id.replace("_", "-")


def package_hash(package_dir: Path) -> str:
    """Deterministic hash over the package data files."""
    digest = hashlib.sha256()
    for name in (
        "topics.json",
        "dependencies.json",
        "cn-curriculum-standards.json",
        "id-aliases.json",
    ):
        path = package_dir / "data" / name
        if not path.is_file():
            raise JuniorImportError(f"missing package file: {path}")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_package(dataset: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Validate the junior package and assert the simplified scope."""
    report = taxonomy_source_import.validate_dataset(dataset, strict_counts=strict)
    errors = list(report["errors"])
    counts = report["counts"]
    if not strict:
        return {"errors": errors, "warnings": report["warnings"], "counts": counts}
    if counts.get("junior_topics") != EXPECTED["topics"]:
        errors.append(f"topics != {EXPECTED['topics']}")
    if counts.get("internal_edges") != EXPECTED["internal_edges"]:
        errors.append(f"internal edges != {EXPECTED['internal_edges']}")
    if counts.get("standards") != EXPECTED["standards"]:
        errors.append(f"standards != {EXPECTED['standards']}")
    if counts.get("standard_refs") != EXPECTED["topic_standards"]:
        errors.append(f"topic standards != {EXPECTED['topic_standards']}")
    if counts.get("cross_stage_edges") != EXPECTED["cross_stage_edges"]:
        errors.append(f"cross-stage edges != {EXPECTED['cross_stage_edges']}")
    return {"errors": errors, "warnings": report["warnings"], "counts": counts}


async def _get_or_create_source(
    db: AsyncSession,
    *,
    package_dir: Path,
    commit: str = SOURCE_COMMIT,
    repo_url: str = SOURCE_REPO,
) -> TaxonomySource:
    content_hash = package_hash(package_dir)
    row = (
        await db.execute(
            select(TaxonomySource).where(
                TaxonomySource.slug == SOURCE_SLUG,
                TaxonomySource.commit_sha == commit,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = TaxonomySource(
            slug=SOURCE_SLUG,
            repo_url=repo_url,
            commit_sha=commit,
            data_version=f"cn-math-taxonomy@{commit}",
            license_status="confirmed",
            license_note=(
                "CC BY-NC 4.0; non-commercial use. Commercial use requires "
                "separate permission from the source author."
            ),
            status="active",
            retrieved_at=_now(),
            content_hash=content_hash,
        )
        db.add(row)
        await db.flush()
    else:
        row.license_status = "confirmed"
        row.content_hash = content_hash
    return row


async def _get_or_create_batch(
    db: AsyncSession, *, source_id: int, note: str, mode: str = "apply"
) -> TaxonomyImportBatch:
    batch = TaxonomyImportBatch(
        source_id=source_id,
        mode=mode,
        status="running",
        started_at=_now(),
        notes=note,
    )
    db.add(batch)
    await db.flush()
    return batch


def _change(
    batch: TaxonomyImportBatch,
    entity_type: str,
    entity_pk: Any,
    operation: str,
    after: dict[str, Any] | None = None,
) -> TaxonomyImportChange:
    return TaxonomyImportChange(
        batch_id=batch.id,
        entity_type=entity_type,
        entity_pk=str(entity_pk),
        operation=operation,
        after_json=after,
    )


async def import_package(
    db: AsyncSession,
    dataset: dict[str, Any],
    *,
    package_dir: Path,
    subject_id: int = 1,
    subject_name: str = "初中数学",
    commit: str = SOURCE_COMMIT,
    repo_url: str = SOURCE_REPO,
    dry_run: bool = False,
    note: str = "junior taxonomy import",
    strict_scope: bool = True,
) -> dict[str, Any]:
    """Materialize the junior package into QuestionBank.

    The whole operation is one transaction: any error rolls back every write.
    Re-running is idempotent (existing rows are skipped, not duplicated).
    """
    validation = validate_package(dataset, strict=strict_scope)
    if validation["errors"]:
        raise JuniorImportError("; ".join(validation["errors"]))

    if dry_run:
        return {
            "mode": "preview",
            "database_writes": 0,
            "subject_id": subject_id,
            "would_rename_subject_to": subject_name,
            "counts": validation["counts"],
        }

    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise JuniorImportError(f"subject {subject_id} not found")

    source = await _get_or_create_source(
        db, package_dir=package_dir, commit=commit, repo_url=repo_url
    )
    batch = await _get_or_create_batch(db, source_id=source.id, note=note)
    summary = {
        "topics_inserted": 0,
        "topics_updated": 0,
        "metadata_upserted": 0,
        "standards_inserted": 0,
        "standards_updated": 0,
        "prerequisites_inserted": 0,
        "prerequisites_skipped": 0,
        "topic_standards_inserted": 0,
        "topic_standards_skipped": 0,
        "cross_stage_edges": 0,
    }

    try:
        # ---------------------------------------------------------- knowledge points
        kp_id_by_external: dict[str, int] = {}
        existing_kps = {
            kp.slug: kp
            for kp in (
                await db.execute(
                    select(KnowledgePoint).where(KnowledgePoint.subject_id == subject_id)
                )
            ).scalars()
        }
        for topic in dataset["junior_topics"]:
            slug = _slug(topic["id"])
            kp = existing_kps.get(slug)
            if kp is None:
                kp = KnowledgePoint(
                    name=topic["name"],
                    slug=slug,
                    subject_id=subject_id,
                    parent_id=None,
                )
                db.add(kp)
                await db.flush()
                existing_kps[slug] = kp
                summary["topics_inserted"] += 1
                db.add(
                    _change(
                        batch,
                        "knowledge_point",
                        kp.id,
                        "insert",
                        {"external_id": topic["id"], "name": topic["name"], "slug": slug},
                    )
                )
            elif kp.name != topic["name"]:
                kp.name = topic["name"]
                summary["topics_updated"] += 1
                db.add(
                    _change(
                        batch,
                        "knowledge_point",
                        kp.id,
                        "update",
                        {"external_id": topic["id"], "name": topic["name"]},
                    )
                )
            kp_id_by_external[topic["id"]] = kp.id

            meta = (
                await db.execute(
                    select(KnowledgePointTaxonomy).where(
                        KnowledgePointTaxonomy.knowledge_point_id == kp.id
                    )
                )
            ).scalar_one_or_none()
            if meta is None:
                meta = KnowledgePointTaxonomy(knowledge_point_id=kp.id)
                db.add(meta)
            meta.source_id = source.id
            meta.external_topic_id = topic["id"]
            meta.stage = STAGE
            meta.grade = topic.get("grade")
            meta.semester = topic.get("semester")
            meta.chapter = topic.get("chapter")
            meta.domain = topic.get("domain")
            meta.is_legacy = False
            meta.is_active = True
            summary["metadata_upserted"] += 1
        await db.flush()

        # ---------------------------------------------------------- standards
        standard_pk: dict[str, int] = {}
        existing_standards = {
            row.standard_id: row
            for row in (
                await db.execute(
                    select(TaxonomyStandard).where(TaxonomyStandard.source_id == source.id)
                )
            ).scalars()
        }
        for item in dataset["standards"]:
            row = existing_standards.get(item["id"])
            content = item.get("text") or item.get("content") or ""
            if row is None:
                row = TaxonomyStandard(
                    source_id=source.id,
                    standard_id=item["id"],
                    content=content,
                )
                db.add(row)
                await db.flush()
                existing_standards[item["id"]] = row
                summary["standards_inserted"] += 1
                db.add(
                    _change(
                        batch,
                        "taxonomy_standard",
                        row.id,
                        "insert",
                        {"standard_id": item["id"]},
                    )
                )
            else:
                summary["standards_updated"] += 1
            row.domain = item.get("domain")
            row.section = item.get("section")
            row.clause = item.get("clause")
            row.content = content
            row.page_or_ref = item.get("page_or_ref")
            row.verbatim = item.get("verbatim")
            row.text_status = item.get("text_status")
            row.is_active = True
            standard_pk[item["id"]] = row.id
        await db.flush()

        # ---------------------------------------------------------- prerequisites
        existing_prereq_keys = {
            key
            for (key,) in (
                await db.execute(
                    select(TaxonomyPrerequisite.current_key).where(
                        TaxonomyPrerequisite.source_id == source.id
                    )
                )
            )
        }
        for edge in dataset["internal_edges"]:
            topic_id = kp_id_by_external[edge["topicId"]]
            prereq_id = kp_id_by_external[edge["prerequisiteId"]]
            key = f"p:{source.id}:{topic_id}:{prereq_id}"
            if key in existing_prereq_keys:
                summary["prerequisites_skipped"] += 1
                continue
            row = TaxonomyPrerequisite(
                source_id=source.id,
                knowledge_point_id=topic_id,
                prerequisite_knowledge_point_id=prereq_id,
                external_topic_id=edge["topicId"],
                external_prerequisite_id=edge["prerequisiteId"],
                strength=edge.get("strength", "hard"),
                raw_evidence={"reason": edge.get("reason")},
                review_status="confirmed",
                batch_id=batch.id,
                revision=1,
                is_current=True,
                current_key=key,
            )
            db.add(row)
            await db.flush()
            existing_prereq_keys.add(key)
            summary["prerequisites_inserted"] += 1
            db.add(
                _change(
                    batch,
                    "taxonomy_prerequisite",
                    row.id,
                    "insert",
                    {
                        "topic": edge["topicId"],
                        "prerequisite": edge["prerequisiteId"],
                        "strength": edge.get("strength", "hard"),
                    },
                )
            )

        # ---------------------------------------------------------- topic standards
        existing_link_keys = {
            key
            for (key,) in (
                await db.execute(
                    select(TaxonomyTopicStandard.current_key).where(
                        TaxonomyTopicStandard.source_id == source.id
                    )
                )
            )
        }
        for topic in dataset["junior_topics"]:
            kp_id = kp_id_by_external[topic["id"]]
            for ref in topic.get("standards") or []:
                pk = standard_pk[ref["id"]]
                key = f"s:{source.id}:{kp_id}:{pk}:1"
                if key in existing_link_keys:
                    summary["topic_standards_skipped"] += 1
                    continue
                row = TaxonomyTopicStandard(
                    source_id=source.id,
                    knowledge_point_id=kp_id,
                    standard_id=pk,
                    confidence=ref.get("confidence", "exact"),
                    review_status="confirmed",
                    batch_id=batch.id,
                    revision=1,
                    is_current=True,
                    current_key=key,
                )
                db.add(row)
                await db.flush()
                existing_link_keys.add(key)
                summary["topic_standards_inserted"] += 1
                db.add(
                    _change(
                        batch,
                        "taxonomy_topic_standard",
                        row.id,
                        "insert",
                        {
                            "topic": topic["id"],
                            "standard_id": ref["id"],
                            "confidence": ref.get("confidence"),
                        },
                    )
                )

        # ---------------------------------------------------------- subject name
        if subject_name and subject.name != subject_name:
            subject.name = subject_name
            summary["subject_renamed"] = subject_name

        changes = summary["topics_inserted"] + summary["topics_updated"] + (
            summary["standards_inserted"]
            + summary["prerequisites_inserted"]
            + summary["topic_standards_inserted"]
        )
        batch.status = "applied" if changes else "validated"
        batch.finished_at = _now()
        batch.summary = {**summary, "validation": validation["counts"]}
        batch_id = batch.id
        source_id = source.id
        final_status = batch.status
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "mode": "apply",
        "batch_id": batch_id,
        "source_id": source_id,
        "status": final_status,
        "change_count": changes,
        "summary": summary,
        "validation": validation["counts"],
    }


async def rollback_batch(db: AsyncSession, batch_id: int) -> dict[str, Any]:
    """Undo one import batch.  Source row and audit change rows are retained."""
    batch = await db.get(TaxonomyImportBatch, batch_id)
    if batch is None:
        raise JuniorImportError(f"batch {batch_id} not found")
    if batch.status == "rolled_back":
        return {"batch_id": batch_id, "status": "rolled_back", "deleted": 0}

    changes = (
        await db.execute(
            select(TaxonomyImportChange).where(
                TaxonomyImportChange.batch_id == batch_id,
                TaxonomyImportChange.operation == "insert",
            )
        )
    ).scalars().all()
    by_type: dict[str, list[int]] = {}
    for change in changes:
        try:
            by_type.setdefault(change.entity_type, []).append(int(change.entity_pk))
        except (TypeError, ValueError):
            continue

    deleted = 0
    try:
        for entity_type, model in (
            ("taxonomy_topic_standard", TaxonomyTopicStandard),
            ("taxonomy_prerequisite", TaxonomyPrerequisite),
            ("knowledge_point", KnowledgePoint),
            ("taxonomy_standard", TaxonomyStandard),
        ):
            ids = by_type.get(entity_type) or []
            if not ids:
                continue
            if model is KnowledgePoint:
                from app.models.question import question_knowledge_points as qkp_table

                # Refuse to delete KPs that still have question links.
                safe: list[int] = []
                for kp_id in ids:
                    links = (
                        await db.execute(
                            select(func.count())
                            .select_from(qkp_table)
                            .where(
                                qkp_table.c.knowledge_point_id == kp_id
                            )
                        )
                    ).scalar_one()
                    if links == 0:
                        safe.append(kp_id)
                ids = safe
            if not ids:
                continue
            result = await db.execute(delete(model).where(model.id.in_(ids)))
            deleted += result.rowcount or 0

        batch.status = "rolled_back"
        batch.finished_at = _now()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"batch_id": batch_id, "status": "rolled_back", "deleted": deleted}


async def purge_legacy(
    db: AsyncSession,
    *,
    subject_id: int = 1,
    subject_name: str | None = "初中数学",
    legacy_max_kp_id: int | None = None,
    legacy_max_question_id: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Remove the legacy knowledge points/questions for a full replacement.

    Keeps ``activity_logs`` and shared media untouched; the log table has no
    foreign key to the deleted entities.
    """
    from app.models.composition import Composition, CompositionNode
    from app.models.question import (
        question_knowledge_points as qkp_table,
        question_tags as qt_table,
    )

    legacy_kp_query = (
        select(KnowledgePoint.id)
        .where(KnowledgePoint.subject_id == subject_id)
        .where(
            ~select(KnowledgePointTaxonomy.knowledge_point_id)
            .where(KnowledgePointTaxonomy.knowledge_point_id == KnowledgePoint.id)
            .exists()
        )
    )
    if legacy_max_kp_id is not None:
        legacy_kp_query = legacy_kp_query.where(KnowledgePoint.id <= legacy_max_kp_id)
    legacy_kp_ids = [row for (row,) in (await db.execute(legacy_kp_query))]

    if legacy_max_question_id is not None:
        # Full replacement: every question up to the legacy ceiling belongs to
        # the old question bank, whether or not it had a knowledge-point link.
        question_query = select(Question.id).where(
            Question.subject_id == subject_id,
            Question.id <= legacy_max_question_id,
        )
    else:
        linked_q = select(qkp_table.c.question_id).where(
            qkp_table.c.knowledge_point_id.in_(legacy_kp_ids)
        )
        question_query = select(Question.id).where(
            Question.subject_id == subject_id,
            Question.id.in_(linked_q),
        )
    question_ids = [row for (row,) in (await db.execute(question_query))]

    composition_ids: list[int] = []
    if question_ids:
        composition_ids = [
            row
            for (row,) in (
                await db.execute(
                    select(CompositionNode.composition_id)
                    .where(CompositionNode.question_id.in_(question_ids))
                    .distinct()
                )
            )
        ]

    counts = {
        "legacy_knowledge_points": len(legacy_kp_ids),
        "legacy_questions": len(question_ids),
        "compositions": len(composition_ids),
        "question_tags": 0,
        "question_links": 0,
        "composition_nodes": 0,
    }
    if question_ids:
        counts["question_tags"] = (
            await db.execute(
                select(func.count())
                .select_from(qt_table)
                .where(qt_table.c.question_id.in_(question_ids))
            )
        ).scalar_one()
        counts["question_links"] = (
            await db.execute(
                select(func.count())
                .select_from(qkp_table)
                .where(qkp_table.c.question_id.in_(question_ids))
            )
        ).scalar_one()
    if composition_ids:
        counts["composition_nodes"] = (
            await db.execute(
                select(func.count())
                .select_from(CompositionNode)
                .where(CompositionNode.composition_id.in_(composition_ids))
            )
        ).scalar_one()

    if dry_run:
        return {"mode": "dry_run", "counts": counts}

    try:
        if composition_ids:
            await db.execute(
                delete(CompositionNode).where(
                    CompositionNode.composition_id.in_(composition_ids)
                )
            )
            await db.execute(
                delete(Composition).where(Composition.id.in_(composition_ids))
            )
        if question_ids:
            await db.execute(
                delete(qt_table).where(qt_table.c.question_id.in_(question_ids))
            )
            await db.execute(
                delete(qkp_table).where(
                    qkp_table.c.question_id.in_(question_ids)
                )
            )
            # break any self-referencing parent links before deleting
            await db.execute(
                update(Question)
                .where(Question.id.in_(question_ids))
                .values(parent_id=None)
            )
            await db.execute(delete(Question).where(Question.id.in_(question_ids)))
        if legacy_kp_ids:
            await db.execute(
                delete(KnowledgePoint).where(KnowledgePoint.id.in_(legacy_kp_ids))
            )
        if subject_name:
            subject = await db.get(Subject, subject_id)
            if subject is not None:
                subject.name = subject_name
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"mode": "apply", "counts": counts}


def manifest_summary(package_dir: Path) -> dict[str, Any]:
    """Read manifest.json for the CLI report (no database access)."""
    path = package_dir / "manifest.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
