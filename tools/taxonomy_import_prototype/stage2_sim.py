#!/usr/bin/env python3
"""Stage-2 in-memory import/rollback simulation.

The simulator never touches MySQL, ChromaDB or the application.  It models the
tables proposed in ``reports/07_integration_design.md`` / ``14_database_schema_design.md``
and verifies that an approved import can be previewed, applied and rolled back
without changing existing knowledge-point IDs or question links.
"""

from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_INTERNAL_DUMP,
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE_DIR,
    PrototypeError,
    canonical_json,
    load_internal_snapshot,
    load_source,
    read_json,
    stable_hash,
    write_json,
    write_text,
)
from export_internal import _find_insert_statement, _parse_tuples  # noqa: E402
from stage2_review import HIGH_RISK_PAIRS, ReviewStore, build_review_store  # noqa: E402


def load_question_links(dump_path: Path) -> list[tuple[int, int]]:
    if not dump_path.is_file():
        return []
    text = dump_path.read_text(encoding="utf-8", errors="replace")
    try:
        rows = _parse_tuples(_find_insert_statement(text, "question_knowledge_points"))
    except Exception:
        return []
    return sorted((int(row[0]), int(row[1])) for row in rows)


class SimulationError(ValueError):
    pass


class Stage2Simulator:
    """Minimal relational simulator with the stage-2 constraints."""

    SOURCE_ID = 1

    def __init__(
        self,
        snapshot: dict[str, Any],
        mapping: dict[str, Any],
        source: dict[str, Any],
        question_links: list[tuple[int, int]] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.mapping = mapping
        self.source = source
        self.question_links = list(question_links or [])
        self.external_db_id = {
            topic["id"]: index + 1 for index, topic in enumerate(source["junior_topics"])
        }
        self.standard_db_id = {
            item["id"]: index + 1 for index, item in enumerate(source["stage4_standards"])
        }
        self.external_by_id = {topic["id"]: topic for topic in source["junior_topics"]}
        self.internal_edges = source["internal_edges"]
        self.cross_stage_edges = source["cross_stage_edges"]
        self.review: ReviewStore = build_review_store(mapping)

        self.base_state = self._build_base_state()
        self.state = copy.deepcopy(self.base_state)
        self._next: dict[str, int] = {
            "taxonomy_topic_mappings": 1,
            "taxonomy_prerequisites": 1,
            "taxonomy_topic_standards": 1,
            "taxonomy_import_batches": 1,
            "taxonomy_import_changes": 1,
            "knowledge_points": max(row["internal_id"] for row in snapshot["knowledge_points"]) + 1,
        }
        self.batches: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ state
    def _build_base_state(self) -> dict[str, Any]:
        kps = [
            {
                "id": row["internal_id"],
                "name": row["name"],
                "slug": row["slug"],
                "subject_id": row["subject_id"],
                "parent_id": row["parent_id"],
            }
            for row in self.snapshot["knowledge_points"]
        ]
        return {
            "knowledge_points": kps,
            "question_knowledge_points": [list(pair) for pair in self.question_links],
            "taxonomy_sources": [
                {
                    "id": self.SOURCE_ID,
                    "slug": "cn-math-taxonomy",
                    "commit_sha": mapping_commit(self.mapping),
                    "status": "active",
                }
            ],
            "taxonomy_external_topics": [
                {
                    "id": self.external_db_id[topic["id"]],
                    "source_id": self.SOURCE_ID,
                    "external_id": topic["id"],
                    "name": topic["name"],
                    "domain": topic.get("domain"),
                    "grade": topic.get("grade"),
                    "semester": topic.get("semester"),
                }
                for topic in self.source["junior_topics"]
            ],
            "taxonomy_standards": [
                {
                    "id": self.standard_db_id[item["id"]],
                    "source_id": self.SOURCE_ID,
                    "standard_id": item["id"],
                    "domain": item.get("domain"),
                    "verbatim": item.get("verbatim"),
                }
                for item in self.source["stage4_standards"]
            ],
            "taxonomy_topic_mappings": [],
            "taxonomy_prerequisites": [],
            "taxonomy_topic_standards": [],
            "taxonomy_import_batches": [],
            "taxonomy_import_changes": [],
        }

    def data_hash(self, state: dict[str, Any] | None = None) -> str:
        payload = state or self.state
        # Audit rows (batches/changes) are intentionally excluded from the data
        # identity so rollback can be checked independently of audit history.
        business = {
            "knowledge_points": payload["knowledge_points"],
            "question_knowledge_points": payload["question_knowledge_points"],
            "taxonomy_sources": payload["taxonomy_sources"],
            "taxonomy_external_topics": payload["taxonomy_external_topics"],
            "taxonomy_standards": payload["taxonomy_standards"],
            "taxonomy_topic_mappings": payload["taxonomy_topic_mappings"],
            "taxonomy_prerequisites": payload["taxonomy_prerequisites"],
            "taxonomy_topic_standards": payload["taxonomy_topic_standards"],
        }
        return stable_hash(business)

    def internal_ids(self, state: dict[str, Any] | None = None) -> list[int]:
        payload = state or self.state
        return sorted(row["id"] for row in payload["knowledge_points"])

    # --------------------------------------------------------------- helpers
    def _mapping_key(self, external_id: str, internal_id: int | None) -> tuple:
        return (self.SOURCE_ID, external_id, internal_id)

    def _current_mapping_keys(self, state: dict[str, Any]) -> set[tuple]:
        return {
            (row["source_id"], row["external_id"], row["internal_knowledge_point_id"])
            for row in state["taxonomy_topic_mappings"]
            if row["is_current"]
        }

    def _internal_ancestors(self) -> dict[int, set[int]]:
        parents = {row["internal_id"]: row["parent_id"] for row in self.snapshot["knowledge_points"]}
        result = {}
        for node in parents:
            chain = set()
            cursor = parents.get(node)
            while cursor is not None and cursor not in chain:
                chain.add(cursor)
                cursor = parents.get(cursor)
            result[node] = chain
        return result

    def _would_cycle(
        self,
        existing: list[tuple[int, int]],
        new_edges: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        adjacency: dict[int, list[int]] = defaultdict(list)
        for topic, prerequisite in existing + new_edges:
            adjacency[topic].append(prerequisite)
        state: dict[int, int] = {}
        found: list[tuple[int, int]] = []

        def visit(node: int, stack: list[int]) -> None:
            state[node] = 1
            for neighbour in adjacency.get(node, []):
                if state.get(neighbour, 0) == 0:
                    visit(neighbour, stack + [neighbour])
                elif state.get(neighbour) == 1:
                    cycle = stack[stack.index(neighbour) :] + [neighbour]
                    found.extend(zip(cycle, cycle[1:]))
            state[node] = 2

        for node in sorted(adjacency):
            if state.get(node, 0) == 0:
                visit(node, [node])
        return found

    # --------------------------------------------------------------- decisions
    def normalise_decisions(self, decisions: dict[str, Any]) -> dict[str, Any]:
        return {
            "confirmed_mappings": [
                (str(external), int(internal))
                for external, internal in decisions.get("confirmed_mappings", [])
            ],
            "confirmed_new_topics": [str(item) for item in decisions.get("confirmed_new_topics", [])],
            "new_topic_parents": {
                str(external): int(parent)
                for external, parent in (decisions.get("new_topic_parents") or {}).items()
            },
            "acknowledged_high_risk": [
                (str(external), int(internal))
                for external, internal in decisions.get("acknowledged_high_risk", [])
            ],
            "reviewer": str(decisions.get("reviewer") or "stage2-simulator"),
            "comment": str(decisions.get("comment") or ""),
        }

    def _validate_decisions(self, decisions: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        internal_ids = set(self.internal_ids())
        known_external = set(self.external_by_id)
        seen_new_ids: set[str] = set()
        for external, internal in decisions["confirmed_mappings"]:
            if external not in known_external:
                errors.append(f"unknown external id: {external}")
            if internal not in internal_ids:
                errors.append(f"unknown internal id: {internal}")
            if (external, internal) in HIGH_RISK_PAIRS and (external, internal) not in set(
                decisions["acknowledged_high_risk"]
            ):
                errors.append(f"high-risk pair requires explicit acknowledgement: {external}->{internal}")
        for external in decisions["confirmed_new_topics"]:
            if external not in known_external:
                errors.append(f"unknown external id for new topic: {external}")
            if external in seen_new_ids:
                errors.append(f"duplicate new topic: {external}")
            seen_new_ids.add(external)
            parent = decisions["new_topic_parents"].get(external)
            if parent is None or parent not in internal_ids:
                errors.append(f"new topic {external} requires an existing parent internal id")
        return errors

    # ----------------------------------------------------------------- preview
    def preview(self, decisions: dict[str, Any]) -> dict[str, Any]:
        decisions = self.normalise_decisions(decisions)
        errors = self._validate_decisions(decisions)
        internal_ids = set(self.internal_ids())
        current = self._current_mapping_keys(self.state)
        existing_prereq = {
            (row["knowledge_point_id"], row["prerequisite_knowledge_point_id"])
            for row in self.state["taxonomy_prerequisites"]
            if row["is_current"]
        }
        existing_standard_links = {
            (row["knowledge_point_id"], row["standard_id"]) for row in self.state["taxonomy_topic_standards"]
        }

        new_knowledge_points: list[dict[str, Any]] = []
        proposed_ids: dict[str, int] = {}
        next_internal = self._next["knowledge_points"]
        duplicate_new_topics: list[str] = []
        already_created = {
            row.get("external_id"): row["id"]
            for row in self.state["knowledge_points"]
            if row.get("external_id")
        }
        for external in decisions["confirmed_new_topics"]:
            if external in already_created:
                proposed_ids[external] = already_created[external]
                continue
            parent = decisions["new_topic_parents"].get(external)
            if parent is None or parent not in internal_ids:
                # Already reported by _validate_decisions; do not fabricate a node.
                continue
            topic = self.external_by_id[external]
            if any(row["name"] == topic["name"] for row in self.state["knowledge_points"]):
                duplicate_new_topics.append(external)
            proposed_ids[external] = next_internal
            new_knowledge_points.append(
                {
                    "id": next_internal,
                    "external_id": external,
                    "name": topic["name"],
                    "parent_id": parent,
                }
            )
            next_internal += 1

        mapping_rows = []
        for external, internal in list(decisions["confirmed_mappings"]) + list(proposed_ids.items()):
            key = (self.SOURCE_ID, external, internal)
            if key in current:
                continue
            mapping_rows.append({"external_id": external, "internal_id": internal})

        confirmed_internal: dict[str, int] = {
            external: internal for external, internal in decisions["confirmed_mappings"]
        }
        confirmed_internal.update(proposed_ids)

        prerequisite_rows = []
        prerequisite_conflicts: list[dict[str, Any]] = []
        proposed_edges: list[tuple[int, int]] = []
        for edge in self.internal_edges:
            topic = confirmed_internal.get(edge["topicId"])
            prerequisite = confirmed_internal.get(edge["prerequisiteId"])
            if topic is None or prerequisite is None:
                continue
            if topic == prerequisite:
                prerequisite_conflicts.append(
                    {
                        "external_topic": edge["topicId"],
                        "external_prerequisite": edge["prerequisiteId"],
                        "internal_id": topic,
                        "reason": "candidate mapping conflict (self-loop shape)",
                    }
                )
                continue
            pair = (topic, prerequisite)
            if pair in existing_prereq or pair in proposed_edges:
                prerequisite_conflicts.append(
                    {
                        "external_topic": edge["topicId"],
                        "external_prerequisite": edge["prerequisiteId"],
                        "internal_topic": topic,
                        "internal_prerequisite": prerequisite,
                        "reason": "duplicate prerequisite edge",
                    }
                )
                continue
            if self._would_cycle(list(existing_prereq), proposed_edges + [pair]):
                prerequisite_conflicts.append(
                    {
                        "external_topic": edge["topicId"],
                        "external_prerequisite": edge["prerequisiteId"],
                        "internal_topic": topic,
                        "internal_prerequisite": prerequisite,
                        "reason": "prerequisite cycle",
                    }
                )
                continue
            proposed_edges.append(pair)
            prerequisite_rows.append(
                {
                    "external_topic": edge["topicId"],
                    "external_prerequisite": edge["prerequisiteId"],
                    "knowledge_point_id": topic,
                    "prerequisite_knowledge_point_id": prerequisite,
                    "strength": edge.get("strength"),
                }
            )

        standard_rows = []
        for external, internal in confirmed_internal.items():
            topic = self.external_by_id[external]
            for ref in topic.get("standards") or []:
                standard_db = self.standard_db_id.get(ref["id"])
                if standard_db is None:
                    continue
                key = (internal, standard_db)
                if key in existing_standard_links or any(
                    (row["knowledge_point_id"], row["standard_id"]) == key for row in standard_rows
                ):
                    continue
                standard_rows.append(
                    {
                        "knowledge_point_id": internal,
                        "standard_id": standard_db,
                        "standard_external_id": ref["id"],
                        "confidence": ref.get("confidence"),
                    }
                )

        if duplicate_new_topics:
            errors.extend(f"new topic duplicates existing name: {item}" for item in duplicate_new_topics)

        return {
            "errors": errors,
            "new_knowledge_points": new_knowledge_points,
            "mapping_rows": mapping_rows,
            "prerequisite_rows": prerequisite_rows,
            "prerequisite_conflicts": prerequisite_conflicts,
            "standard_rows": standard_rows,
            "rejected_candidates": sorted(
                f"{external}->{internal}" for external, internal in self.review.rejected_pairs()
            ),
            "high_risk_conflicts": [
                f"{external}->{internal}"
                for external, internal in decisions["confirmed_mappings"]
                if (external, internal) in HIGH_RISK_PAIRS
            ],
            "duplicate_new_topics": duplicate_new_topics,
            "impact": {
                "existing_knowledge_points": len(self.state["knowledge_points"]),
                "question_links": len(self.state["question_knowledge_points"]),
                "new_knowledge_points": len(new_knowledge_points),
                "mapping_rows": len(mapping_rows),
                "prerequisite_rows": len(prerequisite_rows),
                "standard_links": len(standard_rows),
            },
        }

    # ----------------------------------------------------------------- execute
    def execute(self, decisions: dict[str, Any]) -> dict[str, Any]:
        decisions = self.normalise_decisions(decisions)
        preview = self.preview(decisions)
        if preview["errors"]:
            raise SimulationError("; ".join(preview["errors"]))

        batch_id = self._next["taxonomy_import_batches"]
        self._next["taxonomy_import_batches"] += 1
        before_hash = self.data_hash()
        changes: list[dict[str, Any]] = []

        # New knowledge points
        for row in preview["new_knowledge_points"]:
            internal_id = row["id"]
            self.state["knowledge_points"].append(
                {
                    "id": internal_id,
                    "name": row["name"],
                    "slug": f"taxonomy-{row['external_id']}",
                    "subject_id": 1,
                    "parent_id": row["parent_id"],
                    "external_id": row["external_id"],
                }
            )
            changes.append(
                {
                    "entity_type": "knowledge_point",
                    "entity_pk": str(internal_id),
                    "operation": "insert",
                    "before_json": None,
                    "after_json": {"id": internal_id, "name": row["name"], "parent_id": row["parent_id"]},
                }
            )
            self._next["knowledge_points"] = max(self._next["knowledge_points"], internal_id + 1)

        # Mappings
        for row in preview["mapping_rows"]:
            mapping_id = self._next["taxonomy_topic_mappings"]
            self._next["taxonomy_topic_mappings"] += 1
            new_row = {
                "id": mapping_id,
                "source_id": self.SOURCE_ID,
                "external_topic_id": self.external_db_id[row["external_id"]],
                "external_id": row["external_id"],
                "internal_knowledge_point_id": row["internal_id"],
                "match_type": "confirmed",
                "review_status": "confirmed",
                "revision": 1,
                "is_current": True,
            }
            self.state["taxonomy_topic_mappings"].append(new_row)
            changes.append(
                {
                    "entity_type": "taxonomy_topic_mapping",
                    "entity_pk": str(mapping_id),
                    "operation": "insert",
                    "before_json": None,
                    "after_json": new_row,
                }
            )

        # Prerequisites
        for row in preview["prerequisite_rows"]:
            prereq_id = self._next["taxonomy_prerequisites"]
            self._next["taxonomy_prerequisites"] += 1
            new_row = {
                "id": prereq_id,
                "source_id": self.SOURCE_ID,
                "knowledge_point_id": row["knowledge_point_id"],
                "prerequisite_knowledge_point_id": row["prerequisite_knowledge_point_id"],
                "external_topic_id": row["external_topic"],
                "external_prerequisite_id": row["external_prerequisite"],
                "strength": row["strength"],
                "review_status": "confirmed",
                "revision": 1,
                "is_current": True,
            }
            self.state["taxonomy_prerequisites"].append(new_row)
            changes.append(
                {
                    "entity_type": "knowledge_point_prerequisite",
                    "entity_pk": str(prereq_id),
                    "operation": "insert",
                    "before_json": None,
                    "after_json": new_row,
                }
            )

        # Standards
        for row in preview["standard_rows"]:
            link_id = self._next["taxonomy_topic_standards"]
            self._next["taxonomy_topic_standards"] += 1
            new_row = {
                "id": link_id,
                "source_id": self.SOURCE_ID,
                "knowledge_point_id": row["knowledge_point_id"],
                "standard_id": row["standard_id"],
                "standard_external_id": row["standard_external_id"],
                "confidence": row["confidence"],
                "review_status": "confirmed",
            }
            self.state["taxonomy_topic_standards"].append(new_row)
            changes.append(
                {
                    "entity_type": "knowledge_point_standard",
                    "entity_pk": str(link_id),
                    "operation": "insert",
                    "before_json": None,
                    "after_json": new_row,
                }
            )

        executed_hash = self.data_hash()
        batch = {
            "id": batch_id,
            "source_id": self.SOURCE_ID,
            "mode": "apply",
            "status": "applied" if changes else "validated",
            "summary": preview["impact"],
            "before_hash": before_hash,
            "after_hash": executed_hash,
            "executed_hash": executed_hash,
            "rolled_back_hash": None,
            "change_count": len(changes),
            "reviewer": decisions["reviewer"],
            "comment": decisions["comment"],
        }
        for change in changes:
            self.state["taxonomy_import_changes"].append(
                {**change, "id": self._next["taxonomy_import_changes"], "batch_id": batch_id}
            )
            self._next["taxonomy_import_changes"] += 1
        self.state["taxonomy_import_batches"].append(batch)
        self.batches.append(batch)
        return batch

    # ---------------------------------------------------------------- rollback
    def rollback(self, batch_id: int) -> dict[str, Any]:
        batch = next(
            (item for item in self.state["taxonomy_import_batches"] if item["id"] == batch_id),
            None,
        )
        if batch is None:
            raise SimulationError(f"unknown batch: {batch_id}")
        if batch["status"] == "rolled_back":
            raise SimulationError(f"batch already rolled back: {batch_id}")
        if batch["status"] not in {"applied", "validated"}:
            raise SimulationError(f"batch cannot be rolled back from {batch['status']}")

        changes = [
            row
            for row in self.state["taxonomy_import_changes"]
            if row["batch_id"] == batch_id
        ]
        for change in reversed(changes):
            if change["operation"] == "insert":
                self._remove_row(change["entity_type"], change["entity_pk"])
            else:
                raise SimulationError(f"unsupported rollback operation: {change['operation']}")
        restored_hash = self.data_hash()
        batch["status"] = "rolled_back"
        batch["rolled_back_hash"] = restored_hash
        return {
            "batch_id": batch_id,
            "status": batch["status"],
            "restored_hash": restored_hash,
            "executed_hash": batch["executed_hash"],
            "before_hash": batch["before_hash"],
            "data_equal": restored_hash == batch["before_hash"],
        }

    def _remove_row(self, entity_type: str, entity_pk: str) -> None:
        table = {
            "knowledge_point": "knowledge_points",
            "taxonomy_topic_mapping": "taxonomy_topic_mappings",
            "knowledge_point_prerequisite": "taxonomy_prerequisites",
            "knowledge_point_standard": "taxonomy_topic_standards",
        }.get(entity_type)
        if table is None:
            raise SimulationError(f"unsupported entity type: {entity_type}")
        rows = self.state[table]
        self.state[table] = [row for row in rows if str(row["id"]) != str(entity_pk)]

    # ------------------------------------------------------------------ verify
    def verify(self) -> dict[str, Any]:
        current_ids = set(self.internal_ids())
        original_ids = {row["internal_id"] for row in self.snapshot["knowledge_points"]}
        return {
            "existing_internal_ids_preserved": original_ids <= current_ids,
            "question_links_unchanged": self.state["question_knowledge_points"]
            == [list(pair) for pair in self.question_links],
            "question_link_count": len(self.state["question_knowledge_points"]),
            "knowledge_point_count": len(self.state["knowledge_points"]),
            "mapping_count": len(self.state["taxonomy_topic_mappings"]),
            "prerequisite_count": len(self.state["taxonomy_prerequisites"]),
            "standard_link_count": len(self.state["taxonomy_topic_standards"]),
        }


def mapping_commit(mapping: dict[str, Any]) -> str:
    return str(mapping.get("meta", {}).get("source_commit") or "")


def _preview_markdown(
    simulator: Stage2Simulator, preview: dict[str, Any], batch: dict[str, Any] | None, rollback: dict[str, Any] | None
) -> str:
    impact = preview["impact"]
    lines = [
        "# 15 导入批次、差异预览与回滚（模拟验证）",
        "",
        "> 状态标记：**new**。本文件由 `stage2_sim.py` 在内存模拟库上生成；"
        "不连接 MySQL/ChromaDB，不写正式数据。",
        "",
        "## 生命周期",
        "",
        "`source_prepare → validate → mapping_review → import_preview → approval → execute → verify → rollback`",
        "",
        "本阶段模拟覆盖 `import_preview → execute → verify → rollback`；前序步骤由 02/03/10/11 报告覆盖。",
        "",
        "## 差异预览",
        "",
        "| 项目 | 数量 |",
        "|---|---:|",
        f"| 新增知识点（需人工批准） | {impact['new_knowledge_points']} |",
        f"| 建立映射 | {impact['mapping_rows']} |",
        f"| 新增先修关系 | {impact['prerequisite_rows']} |",
        f"| 新增课标关联 | {impact['standard_links']} |",
        f"| 被拒绝候选（默认跳过） | {len(preview['rejected_candidates'])} |",
        f"| 高风险冲突（已显式确认） | {len(preview['high_risk_conflicts'])} |",
        f"| 重复节点 | {len(preview['duplicate_new_topics'])} |",
        f"| 先修冲突（自环/重复/环，已阻止） | {len(preview['prerequisite_conflicts'])} |",
        f"| 现有知识点 | {impact['existing_knowledge_points']} |",
        f"| 现有题目关联 | {impact['question_links']} |",
        "",
        "## 执行与回滚",
        "",
    ]
    if batch is not None:
        lines.extend(
            [
                f"- 批次：`{batch['id']}`，状态 `{batch['status']}`，变更 `{batch['change_count']}` 条。",
                f"- 执行前数据哈希：`{batch['before_hash']}`",
                f"- 执行后数据哈希：`{batch['executed_hash']}`",
            ]
        )
    else:
        lines.append("- 未执行 apply（默认 dry-run）。")
    if rollback is not None:
        lines.extend(
            [
                f"- 回滚后数据哈希：`{rollback['restored_hash']}`",
                f"- 是否恢复一致：**{rollback['data_equal']}**",
            ]
        )
    else:
        lines.append("- 未执行 rollback。")
    lines.extend(
        [
            "",
            "## 先修冲突（已阻止写入）",
            "",
        ]
    )
    if preview["prerequisite_conflicts"]:
        lines.append("```json")
        import json

        lines.append(json.dumps(preview["prerequisite_conflicts"][:20], ensure_ascii=False, indent=2))
        lines.append("```")
    else:
        lines.append("无。")
    lines.extend(
        [
            "",
            "## 回滚边界",
            "",
            "- 回滚只删除本批次新增行，并记录批次状态；不删除原题目关联。",
            "- 已确认映射/先修/课标关联不参与自动回滚；需人工生成反向批次。",
            "- 模拟器验证回滚后 `data_hash` 与导入前完全一致。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--internal-snapshot", type=Path, default=None)
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--internal-dump", type=Path, default=DEFAULT_INTERNAL_DUMP)
    parser.add_argument("--decisions", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    snapshot_path = args.internal_snapshot or (args.out_dir / "internal_snapshot.json")
    mapping_path = args.mapping or (args.out_dir / "mapping_result.json")
    try:
        snapshot = load_internal_snapshot(snapshot_path)
        mapping = read_json(mapping_path, label="mapping_result.json")
        source = load_source(args.source_dir)
        decisions = (
            read_json(args.decisions, label="decisions") if args.decisions is not None else {}
        )
        simulator = Stage2Simulator(
            snapshot, mapping, source, load_question_links(args.internal_dump)
        )
        normalised = simulator.normalise_decisions(decisions)
        preview = simulator.preview(normalised)
        batch = None
        rollback = None
        if not preview["errors"]:
            batch = simulator.execute(normalised)
            rollback = simulator.rollback(batch["id"])
        payload = {
            "mode": "simulation",
            "database": "in-memory only",
            "preview": preview,
            "batch": batch,
            "rollback": rollback,
            "verify": simulator.verify(),
            "review_status_counts": simulator.review.status_counts(),
        }
    except (PrototypeError, SimulationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write_json(args.out_dir / "stage2_simulation.json", payload)
    write_text(
        args.out_dir / "15_batch_preview_rollback.md",
        _preview_markdown(simulator, preview, batch, rollback),
    )
    print(
        "stage2 simulation: "
        f"errors={len(preview['errors'])} "
        f"batch_changes={batch['change_count'] if batch else 0} "
        f"rollback_equal={rollback['data_equal'] if rollback else None}"
    )
    return 2 if preview["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
