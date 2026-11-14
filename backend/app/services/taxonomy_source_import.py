"""Stage-5 external dataset import (taxonomy side only).

This service never creates/updates/deletes internal knowledge points or question
links.  It only writes ``taxonomy_*`` tables.  A license gate lives in the CLI;
the service itself is reusable by tests with synthetic data.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_point import KnowledgePoint
from app.models.taxonomy import (
    TaxonomyExternalRelation,
    TaxonomyExternalTopic,
    TaxonomyExternalTopicStandard,
    TaxonomyImportBatch,
    TaxonomyImportChange,
    TaxonomySource,
    TaxonomyStandard,
    TaxonomyTopicMapping,
)

JUNIOR_GRADES = (7, 8, 9)
MATH_DOMAINS = ("数与代数", "图形与几何", "统计与概率", "综合与实践")
EXPECTED_JUNIOR = 315
EXPECTED_INTERNAL_EDGES = 563
EXPECTED_CROSS_STAGE_EDGES = 45
EXPECTED_STAGE4_STANDARDS = 157
HIGH_RISK_PAIRS = {("cnm_093", 10), ("cnm_200", 19), ("cnm_208", 10)}
SOURCE_SLUG = "cn-math-taxonomy"


class DatasetError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise DatasetError(f"file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"invalid JSON: {path}: {exc}") from exc


def load_dataset(
    source_dir: Path,
    mapping_path: Path | None = None,
    *,
    include_cross_stage: bool = True,
) -> dict[str, Any]:
    source_dir = Path(source_dir)
    topics = _read_json(source_dir / "data" / "topics.json")
    dependencies = _read_json(source_dir / "data" / "dependencies.json")
    standards_doc = _read_json(source_dir / "data" / "cn-curriculum-standards.json")
    aliases_doc = _read_json(source_dir / "data" / "id-aliases.json")
    if not isinstance(topics, list) or not isinstance(dependencies, list):
        raise DatasetError("topics/dependencies must be arrays")
    if not isinstance(standards_doc, dict) or not isinstance(standards_doc.get("items"), list):
        raise DatasetError("standards file must contain an items array")
    aliases = aliases_doc.get("aliases") if isinstance(aliases_doc, dict) else None
    if not isinstance(aliases, dict):
        raise DatasetError("id-aliases must contain an aliases object")

    topic_by_id = {topic["id"]: topic for topic in topics if "id" in topic}
    junior = sorted(
        [
            topic
            for topic in topics
            if str(topic.get("id", "")).startswith("cnm_")
            and topic.get("grade") in JUNIOR_GRADES
        ],
        key=lambda item: item["id"],
    )
    junior_ids = {topic["id"] for topic in junior}
    primary_ids = {
        topic["id"]
        for topic in topics
        if str(topic.get("id", "")).startswith("cnm_")
        and 1 <= int(topic.get("grade") or 0) <= 6
    }
    internal_edges = [
        edge
        for edge in dependencies
        if edge.get("topicId") in junior_ids and edge.get("prerequisiteId") in junior_ids
    ]
    cross_edges = [
        edge
        for edge in dependencies
        if edge.get("topicId") in junior_ids and edge.get("prerequisiteId") in primary_ids
    ]
    # The simplified deployment keeps only junior-internal prerequisites; the
    # primary-to-junior edges stay in the source package but are not imported.
    if not include_cross_stage:
        cross_edges = []
    stage4_standards = sorted(
        [
            item
            for item in standards_doc["items"]
            if str(item.get("id", "")).split(":")[-1].startswith("4.")
            and item.get("domain") in MATH_DOMAINS
        ],
        key=lambda item: item["id"],
    )
    mapping = _read_json(Path(mapping_path)) if mapping_path else None
    return {
        "source_dir": str(source_dir),
        "topics": topics,
        "topic_by_id": topic_by_id,
        "junior_topics": junior,
        "junior_ids": junior_ids,
        "primary_ids": primary_ids,
        "dependencies": dependencies,
        "internal_edges": internal_edges,
        "cross_stage_edges": cross_edges,
        "standards": stage4_standards,
        "aliases": aliases,
        "mapping": mapping,
        "include_cross_stage": include_cross_stage,
    }


def subset_dataset(
    dataset: dict[str, Any], limit: int, mapping: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return a deterministic small slice for a pilot import (no DB writes)."""
    if limit <= 0:
        raise DatasetError("limit must be positive")
    topics = dataset["junior_topics"][:limit]
    ids = {topic["id"] for topic in topics}
    internal_edges = [edge for edge in dataset["internal_edges"] if edge["topicId"] in ids]
    cross_edges = [edge for edge in dataset["cross_stage_edges"] if edge["topicId"] in ids]
    referenced_standard_ids = {
        ref["id"]
        for topic in topics
        for ref in (topic.get("standards") or [])
    }
    standards = [
        item for item in dataset["standards"] if item["id"] in referenced_standard_ids
    ]
    subset = {
        **dataset,
        "junior_topics": topics,
        "standards": standards,
        "junior_ids": ids,
        "internal_edges": internal_edges,
        "cross_stage_edges": cross_edges,
    }
    subset_mapping = None
    if mapping is not None:
        subset_mapping = {
            **mapping,
            "external_topics": [
                row for row in mapping.get("external_topics", []) if row.get("external_id") in ids
            ],
        }
    return subset, subset_mapping


def _cycle(nodes: set[str], edges: Iterable[dict[str, Any]]) -> list[str] | None:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["topicId"]].append(edge["prerequisiteId"])
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> list[str] | None:
        state[node] = 1
        for neighbour in adjacency.get(node, []):
            if state.get(neighbour, 0) == 0:
                result = visit(neighbour, stack + [neighbour])
                if result:
                    return result
            elif state.get(neighbour) == 1:
                return stack[stack.index(neighbour) :] + [neighbour]
        state[node] = 2
        return None

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            result = visit(node, [node])
            if result:
                return result
    return None


def validate_dataset(dataset: dict[str, Any], *, strict_counts: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    junior = dataset["junior_topics"]
    topics = dataset["topics"]
    topic_by_id = dataset["topic_by_id"]
    duplicate_ids = [
        topic_id for topic_id, count in Counter(topic.get("id") for topic in topics).items() if count > 1
    ]
    if duplicate_ids:
        errors.append(f"duplicate topic ids: {sorted(duplicate_ids)[:10]}")
    if strict_counts and len(junior) != EXPECTED_JUNIOR:
        errors.append(f"junior topics {len(junior)} != {EXPECTED_JUNIOR}")
    bad_domains = sorted({str(topic.get("domain")) for topic in junior if topic.get("domain") not in MATH_DOMAINS})
    if bad_domains:
        errors.append(f"unexpected domains: {bad_domains}")
    if any(topic.get("external") for topic in junior):
        errors.append("junior topics contain external=true placeholders")

    internal_edges = dataset["internal_edges"]
    cross_edges = dataset["cross_stage_edges"]
    if strict_counts and len(internal_edges) != EXPECTED_INTERNAL_EDGES:
        errors.append(f"internal edges {len(internal_edges)} != {EXPECTED_INTERNAL_EDGES}")
    expected_cross = (
        EXPECTED_CROSS_STAGE_EDGES
        if dataset.get("include_cross_stage", True)
        else 0
    )
    if strict_counts and len(cross_edges) != expected_cross:
        errors.append(f"cross-stage edges {len(cross_edges)} != {expected_cross}")

    alias_ids = set(dataset["aliases"])
    missing_endpoints = []
    for edge in dataset["dependencies"]:
        for side in ("topicId", "prerequisiteId"):
            value = edge.get(side)
            if value not in topic_by_id and value not in alias_ids:
                missing_endpoints.append((edge.get("topicId"), edge.get("prerequisiteId"), side, value))
    if missing_endpoints:
        errors.append(f"{len(missing_endpoints)} dependency endpoints missing")
    edge_keys = [(edge["topicId"], edge["prerequisiteId"]) for edge in dataset["dependencies"]]
    duplicates = [key for key, count in Counter(edge_keys).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate dependency edges: {len(duplicates)}")
    self_loops = [edge for edge in dataset["dependencies"] if edge["topicId"] == edge["prerequisiteId"]]
    if self_loops:
        errors.append(f"self-loop dependency edges: {len(self_loops)}")
    cycle = _cycle(dataset["junior_ids"], internal_edges)
    if cycle:
        errors.append(f"dependency cycle: {cycle}")
    bad_strength = sorted(
        {str(edge.get("strength")) for edge in dataset["dependencies"] if edge.get("strength") not in {"hard", "soft"}}
    )
    if bad_strength:
        errors.append(f"unexpected strengths: {bad_strength}")

    standards = dataset["standards"]
    if strict_counts and len(standards) != EXPECTED_STAGE4_STANDARDS:
        errors.append(f"stage4 standards {len(standards)} != {EXPECTED_STAGE4_STANDARDS}")
    standard_ids = {item["id"] for item in standards}
    refs = [
        (topic["id"], ref.get("id"), ref.get("confidence"))
        for topic in junior
        for ref in (topic.get("standards") or [])
    ]
    missing_refs = sorted({ref[1] for ref in refs if ref[1] not in standard_ids})
    if missing_refs:
        errors.append(f"standard refs missing: {missing_refs[:10]}")
    bad_confidence = sorted({ref[2] for ref in refs if ref[2] not in {"exact", "inferred"}})
    if bad_confidence:
        errors.append(f"unexpected confidence values: {bad_confidence}")
    topics_without_standards = sorted(topic["id"] for topic in junior if not topic.get("standards"))
    if topics_without_standards:
        warnings.append(f"{len(topics_without_standards)} topics without standards: {topics_without_standards}")

    mapping_errors = _validate_mapping(dataset.get("mapping"), topic_by_id, strict_counts=strict_counts)
    errors.extend(mapping_errors["errors"])
    warnings.extend(mapping_errors["warnings"])

    return {
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "topics_total": len(topics),
            "junior_topics": len(junior),
            "internal_edges": len(internal_edges),
            "cross_stage_edges": len(cross_edges),
            "standards": len(standards),
            "standard_refs": len(refs),
            "exact_refs": sum(1 for ref in refs if ref[2] == "exact"),
            "inferred_refs": sum(1 for ref in refs if ref[2] == "inferred"),
            "topics_without_standards": topics_without_standards,
            "aliases": len(alias_ids),
            "mapping_rows": len((dataset.get("mapping") or {}).get("external_topics", [])),
            "mapping_candidates": mapping_errors["candidate_pairs"],
            "new_topic_rows": mapping_errors["new_topic_rows"],
        },
    }


def _validate_mapping(mapping: Any, topic_by_id: dict[str, Any], *, strict_counts: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if mapping is None:
        return {"errors": errors, "warnings": ["mapping file not provided"], "candidate_pairs": 0, "new_topic_rows": 0}
    rows = mapping.get("external_topics") if isinstance(mapping, dict) else None
    if not isinstance(rows, list):
        return {"errors": ["mapping.external_topics must be an array"], "warnings": [], "candidate_pairs": 0, "new_topic_rows": 0}
    seen = set()
    pairs = 0
    new_topics = 0
    for row in rows:
        external_id = row.get("external_id")
        if external_id not in topic_by_id:
            errors.append(f"mapping unknown external id: {external_id}")
            continue
        if external_id in seen:
            errors.append(f"mapping duplicate external id: {external_id}")
        seen.add(external_id)
        if row.get("review_status") not in {"pending_review", "new_topic_pending"}:
            errors.append(f"{external_id}: mapping must stay pending")
        candidates = row.get("candidates") or []
        if candidates:
            pairs += len(candidates)
            for candidate in candidates:
                if candidate.get("internal_id") is None:
                    errors.append(f"{external_id}: candidate has no internal id")
                if (external_id, candidate.get("internal_id")) in HIGH_RISK_PAIRS and not candidate.get("high_risk"):
                    warnings.append(f"{external_id}: forced high-risk flag")
        else:
            new_topics += 1
            if row.get("match_type") != "new_topic":
                errors.append(f"{external_id}: no candidates but not new_topic")
    missing = sorted(set(topic_by_id) - seen) if strict_counts and len(topic_by_id) == EXPECTED_JUNIOR else []
    if missing:
        errors.append(f"mapping missing {len(missing)} junior topics")
    return {
        "errors": errors,
        "warnings": warnings,
        "candidate_pairs": pairs,
        "new_topic_rows": new_topics,
    }


async def preview_import(
    db: AsyncSession | None,
    dataset: dict[str, Any],
    *,
    source_slug: str = SOURCE_SLUG,
    commit_sha: str,
    mapping: dict[str, Any] | None,
    strict_counts: bool = True,
) -> dict[str, Any]:
    validation = validate_dataset({**dataset, "mapping": mapping}, strict_counts=strict_counts)
    counts = {
        "topics_to_import": len(dataset["junior_topics"]),
        "standards_to_import": len(dataset["standards"]),
        "internal_relations_to_import": len(dataset["internal_edges"]),
        "cross_stage_relations_to_import": len(dataset["cross_stage_edges"]),
        "standard_refs_to_import": sum(len(topic.get("standards") or []) for topic in dataset["junior_topics"]),
        "mapping_rows_to_import": 0,
        "new_topic_rows_to_import": 0,
    }
    if mapping:
        for row in mapping.get("external_topics", []):
            if row.get("candidates"):
                counts["mapping_rows_to_import"] += len(row["candidates"])
            else:
                counts["new_topic_rows_to_import"] += 1
    existing = 0
    if db is not None:
        existing = (
            await db.execute(
                select(TaxonomySource).where(
                    TaxonomySource.slug == source_slug,
                    TaxonomySource.commit_sha == commit_sha,
                )
            )
        ).scalars().first() is not None
    return {
        "validation": validation,
        "source_slug": source_slug,
        "commit_sha": commit_sha,
        "source_exists": bool(existing),
        "counts": counts,
    }


async def _get_or_create_source(db: AsyncSession, *, source_slug: str, source_meta: dict[str, Any]) -> tuple[TaxonomySource, bool]:
    source = (
        await db.execute(
            select(TaxonomySource).where(
                TaxonomySource.slug == source_slug,
                TaxonomySource.commit_sha == source_meta["commit_sha"],
            )
        )
    ).scalars().first()
    if source is not None:
        return source, False
    source = TaxonomySource(
        slug=source_slug,
        repo_url=source_meta["repo_url"],
        commit_sha=source_meta["commit_sha"],
        data_version=source_meta.get("data_version"),
        license_status=source_meta.get("license_status", "unconfirmed"),
        license_note=source_meta.get("license_note"),
        content_hash=source_meta.get("content_hash"),
        retrieved_at=_now(),
    )
    db.add(source)
    await db.flush()
    return source, True


async def import_dataset(
    db: AsyncSession,
    dataset: dict[str, Any],
    *,
    source_slug: str = SOURCE_SLUG,
    source_meta: dict[str, Any],
    mapping: dict[str, Any] | None,
    mode: str = "apply",
    strict_counts: bool = True,
) -> dict[str, Any]:
    if mode not in {"preview", "apply"}:
        raise DatasetError("mode must be preview or apply")
    preview = await preview_import(
        db if mode == "apply" else None,
        dataset,
        source_slug=source_slug,
        commit_sha=source_meta["commit_sha"],
        mapping=mapping,
        strict_counts=strict_counts,
    )
    if mode == "preview":
        return {"mode": "preview", "database_writes": 0, **preview}
    if preview["validation"]["errors"]:
        raise DatasetError("dataset validation failed: " + "; ".join(preview["validation"]["errors"]))

    batch = TaxonomyImportBatch(
        source_id=0,
        mode="apply",
        status="validated",
        summary={"stage": 5, "kind": "external_source_import"},
        conflicts=[],
        notes="stage5 external dataset",
        started_at=_now(),
    )
    changes: list[TaxonomyImportChange] = []

    try:
        source, source_created = await _get_or_create_source(
            db, source_slug=source_slug, source_meta=source_meta
        )
        batch.source_id = source.id
        db.add(batch)
        await db.flush()
        if source_created:
            changes.append(
                TaxonomyImportChange(
                    batch_id=batch.id,
                    entity_type="taxonomy_source",
                    entity_pk=str(source.id),
                    operation="insert",
                    after_json={"id": source.id, "slug": source.slug, "commit_sha": source.commit_sha},
                )
            )

        # External topics
        existing_topics = {
            row.external_id: row
            for row in (
                await db.execute(
                    select(TaxonomyExternalTopic).where(TaxonomyExternalTopic.source_id == source.id)
                )
            ).scalars().all()
        }
        topic_db_id: dict[str, int] = {}
        for topic in dataset["junior_topics"]:
            row = existing_topics.get(topic["id"])
            is_new = row is None
            if row is None:
                row = TaxonomyExternalTopic(source_id=source.id, external_id=topic["id"], name=topic["name"])
                db.add(row)
                await db.flush()
            row.name = topic["name"]
            row.domain = topic.get("domain")
            row.grade = topic.get("grade")
            row.semester = topic.get("semester")
            row.chapter = topic.get("chapter")
            row.topic_type = topic.get("type")
            row.description = topic.get("description")
            row.mastery_criteria = topic.get("mastery_criteria")
            row.raw = topic
            row.external = bool(topic.get("external"))
            topic_db_id[topic["id"]] = row.id
            if is_new:
                changes.append(
                    TaxonomyImportChange(
                        batch_id=batch.id,
                        entity_type="taxonomy_external_topic",
                        entity_pk=str(row.id),
                        operation="insert",
                        after_json={"id": row.id, "external_id": row.external_id},
                    )
                )

        # Standards
        existing_standards = {
            row.standard_id: row
            for row in (
                await db.execute(
                    select(TaxonomyStandard).where(TaxonomyStandard.source_id == source.id)
                )
            ).scalars().all()
        }
        standard_db_id: dict[str, int] = {}
        for item in dataset["standards"]:
            row = existing_standards.get(item["id"])
            is_new = row is None
            if row is None:
                row = TaxonomyStandard(source_id=source.id, standard_id=item["id"], content=item.get("content", ""))
                db.add(row)
                await db.flush()
            row.domain = item.get("domain")
            row.section = item.get("section")
            row.clause = item.get("clause")
            row.content = item.get("text") or item.get("content") or ""
            row.page_or_ref = item.get("page_or_ref")
            row.verbatim = item.get("verbatim")
            row.text_status = item.get("text_status")
            row.default_confidence = None
            row.revision = item.get("revision")
            standard_db_id[item["id"]] = row.id
            if is_new:
                changes.append(
                    TaxonomyImportChange(
                        batch_id=batch.id,
                        entity_type="taxonomy_standard",
                        entity_pk=str(row.id),
                        operation="insert",
                        after_json={"id": row.id, "standard_id": row.standard_id},
                    )
                )

        # External relations (563 + 45)
        existing_relations = {
            (row.topic_external_id, row.prerequisite_external_id, row.relation_kind): row
            for row in (
                await db.execute(
                    select(TaxonomyExternalRelation).where(TaxonomyExternalRelation.source_id == source.id)
                )
            ).scalars().all()
        }
        for kind, edges in (("internal", dataset["internal_edges"]), ("cross_stage", dataset["cross_stage_edges"])):
            for edge in edges:
                key = (edge["topicId"], edge["prerequisiteId"], kind)
                if key in existing_relations:
                    continue
                row = TaxonomyExternalRelation(
                    source_id=source.id,
                    topic_external_id=edge["topicId"],
                    prerequisite_external_id=edge["prerequisiteId"],
                    strength=edge.get("strength", "hard"),
                    relation_kind=kind,
                    reason=edge.get("reason"),
                    raw=edge,
                )
                db.add(row)
                await db.flush()
                existing_relations[key] = row
                changes.append(
                    TaxonomyImportChange(
                        batch_id=batch.id,
                        entity_type="taxonomy_external_relation",
                        entity_pk=str(row.id),
                        operation="insert",
                        after_json={
                            "id": row.id,
                            "kind": kind,
                            "topic": edge["topicId"],
                            "prerequisite": edge["prerequisiteId"],
                        },
                    )
                )

        # External topic -> standard refs (383)
        existing_refs = {
            (row.external_topic_id, row.standard_id)
            for row in (
                await db.execute(
                    select(TaxonomyExternalTopicStandard).where(
                        TaxonomyExternalTopicStandard.source_id == source.id
                    )
                )
            ).scalars().all()
        }
        for topic in dataset["junior_topics"]:
            for ref in topic.get("standards") or []:
                key = (topic["id"], ref["id"])
                if key in existing_refs or ref["id"] not in standard_db_id:
                    continue
                row = TaxonomyExternalTopicStandard(
                    source_id=source.id,
                    external_topic_id=topic["id"],
                    standard_id=ref["id"],
                    confidence=ref.get("confidence", "exact"),
                    raw=ref,
                )
                db.add(row)
                await db.flush()
                existing_refs.add(key)
                changes.append(
                    TaxonomyImportChange(
                        batch_id=batch.id,
                        entity_type="taxonomy_external_topic_standard",
                        entity_pk=str(row.id),
                        operation="insert",
                        after_json={
                            "id": row.id,
                            "external_topic": topic["id"],
                            "standard": ref["id"],
                        },
                    )
                )

        # Mapping queue (12 candidates + 303 new_topic rows)
        if mapping is not None:
            internal_ids = {
                row.id for row in (await db.execute(select(KnowledgePoint))).scalars().all()
            }
            current_keys = {
                row.current_key
                for row in (
                    await db.execute(
                        select(TaxonomyTopicMapping).where(
                            TaxonomyTopicMapping.source_id == source.id,
                            TaxonomyTopicMapping.is_current.is_(True),
                        )
                    )
                ).scalars().all()
            }
            for row in mapping.get("external_topics", []):
                external_id = row["external_id"]
                external_db = topic_db_id.get(external_id)
                if external_db is None:
                    continue
                candidates = row.get("candidates") or []
                if not candidates:
                    key = f"m:{source.id}:{external_db}:0"
                    if key in current_keys:
                        continue
                    mapping_row = TaxonomyTopicMapping(
                        source_id=source.id,
                        external_topic_id=external_db,
                        internal_knowledge_point_id=None,
                        match_type="new_topic",
                        reason=row.get("reason", ""),
                        review_status="new_topic_pending",
                        is_current=True,
                        current_key=key,
                    )
                    db.add(mapping_row)
                    await db.flush()
                    current_keys.add(key)
                    changes.append(
                        TaxonomyImportChange(
                            batch_id=batch.id,
                            entity_type="taxonomy_topic_mapping",
                            entity_pk=str(mapping_row.id),
                            operation="insert",
                            after_json={"id": mapping_row.id, "external_id": external_id, "match_type": "new_topic"},
                        )
                    )
                    continue
                for candidate in candidates:
                    internal_id = candidate.get("internal_id")
                    if internal_id not in internal_ids:
                        raise DatasetError(
                            f"mapping internal id {internal_id} does not exist for {external_id}"
                        )
                    key = f"m:{source.id}:{external_db}:{internal_id}"
                    if key in current_keys:
                        continue
                    high_risk = bool(candidate.get("high_risk")) or (
                        external_id, internal_id
                    ) in HIGH_RISK_PAIRS
                    mapping_row = TaxonomyTopicMapping(
                        source_id=source.id,
                        external_topic_id=external_db,
                        internal_knowledge_point_id=internal_id,
                        match_type=row.get("match_type", "semantic"),
                        confidence=candidate.get("confidence"),
                        reason=candidate.get("reason", ""),
                        conflict=bool(candidate.get("conflict")),
                        high_risk=high_risk,
                        risk=candidate.get("risk"),
                        review_status="pending_review",
                        is_current=True,
                        current_key=key,
                    )
                    db.add(mapping_row)
                    await db.flush()
                    current_keys.add(key)
                    changes.append(
                        TaxonomyImportChange(
                            batch_id=batch.id,
                            entity_type="taxonomy_topic_mapping",
                            entity_pk=str(mapping_row.id),
                            operation="insert",
                            after_json={"id": mapping_row.id, "external_id": external_id, "internal_id": internal_id},
                        )
                    )

        for change in changes:
            db.add(change)
        batch.status = "applied" if changes else "validated"
        batch.finished_at = _now()
        batch.summary = {
            **(batch.summary or {}),
            "inserted": len(changes),
            "topics": len(dataset["junior_topics"]),
            "internal_relations": len(dataset["internal_edges"]),
            "cross_stage_relations": len(dataset["cross_stage_edges"]),
            "standards": len(dataset["standards"]),
        }
        await db.commit()
        await db.refresh(batch)
        return {
            "mode": "apply",
            "batch_id": batch.id,
            "status": batch.status,
            "change_count": len(changes),
            "summary": batch.summary,
            "validation": preview["validation"],
        }
    except Exception:
        await db.rollback()
        raise


async def rollback_source_batch(db: AsyncSession, *, batch_id: int) -> dict[str, Any]:
    batch = await db.get(TaxonomyImportBatch, batch_id)
    if batch is None:
        raise DatasetError(f"batch not found: {batch_id}")
    if batch.status not in {"applied", "validated"}:
        raise DatasetError(f"batch cannot be rolled back from {batch.status}")
    changes = (
        await db.execute(
            select(TaxonomyImportChange)
            .where(TaxonomyImportChange.batch_id == batch_id)
            .order_by(TaxonomyImportChange.id.desc())
        )
    ).scalars().all()
    table_map = {
        # The source row is retained for audit/versioning; only imported data is
        # removed.  Batches still reference it (RESTRICT).
        "taxonomy_external_topic": TaxonomyExternalTopic,
        "taxonomy_standard": TaxonomyStandard,
        "taxonomy_external_relation": TaxonomyExternalRelation,
        "taxonomy_external_topic_standard": TaxonomyExternalTopicStandard,
        "taxonomy_topic_mapping": TaxonomyTopicMapping,
    }
    try:
        for change in changes:
            model = table_map.get(change.entity_type)
            if model is None or change.operation != "insert":
                continue
            row = await db.get(model, int(change.entity_pk))
            if row is not None:
                await db.delete(row)
                await db.flush()
        batch.status = "rolled_back"
        batch.finished_at = _now()
        rollback_batch = TaxonomyImportBatch(
            source_id=batch.source_id,
            mode="apply",
            status="rolled_back",
            summary={"rollback_of": batch.id, "removed": len(changes)},
            rollback_of_batch_id=batch.id,
        )
        db.add(rollback_batch)
        await db.commit()
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "removed_changes": len(changes),
            "rollback_batch_id": rollback_batch.id,
        }
    except Exception:
        await db.rollback()
        raise


# ---------------------------------------------------------------------------
# Read-only queries for the external dataset
# ---------------------------------------------------------------------------


async def list_external_topics(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    grade: int | None = None,
    domain: str | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conditions = []
    if source_id is not None:
        conditions.append(TaxonomyExternalTopic.source_id == source_id)
    if grade is not None:
        conditions.append(TaxonomyExternalTopic.grade == grade)
    if domain:
        conditions.append(TaxonomyExternalTopic.domain == domain)
    if search:
        conditions.append(TaxonomyExternalTopic.name.ilike(f"%{search}%"))
    rows = (
        await db.execute(
            select(TaxonomyExternalTopic)
            .where(*conditions)
            .order_by(TaxonomyExternalTopic.external_id)
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "external_id": row.external_id,
            "name": row.name,
            "domain": row.domain,
            "grade": row.grade,
            "semester": row.semester,
            "chapter": row.chapter,
            "topic_type": row.topic_type,
            "is_active": row.is_active,
        }
        for row in rows
    ]


async def list_external_relations(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    relation_kind: str | None = None,
    strength: str | None = None,
    skip: int = 0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    conditions = []
    if source_id is not None:
        conditions.append(TaxonomyExternalRelation.source_id == source_id)
    if relation_kind:
        conditions.append(TaxonomyExternalRelation.relation_kind == relation_kind)
    if strength:
        conditions.append(TaxonomyExternalRelation.strength == strength)
    rows = (
        await db.execute(
            select(TaxonomyExternalRelation)
            .where(*conditions)
            .order_by(TaxonomyExternalRelation.topic_external_id)
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "topic_external_id": row.topic_external_id,
            "prerequisite_external_id": row.prerequisite_external_id,
            "strength": row.strength,
            "relation_kind": row.relation_kind,
            "reason": row.reason,
        }
        for row in rows
    ]


async def list_external_topic_standards(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    external_topic_id: str | None = None,
    skip: int = 0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    conditions = []
    if source_id is not None:
        conditions.append(TaxonomyExternalTopicStandard.source_id == source_id)
    if external_topic_id:
        conditions.append(TaxonomyExternalTopicStandard.external_topic_id == external_topic_id)
    rows = (
        await db.execute(
            select(TaxonomyExternalTopicStandard)
            .where(*conditions)
            .order_by(TaxonomyExternalTopicStandard.external_topic_id)
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "external_topic_id": row.external_topic_id,
            "standard_id": row.standard_id,
            "confidence": row.confidence,
            "review_status": row.review_status,
        }
        for row in rows
    ]
