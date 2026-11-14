#!/usr/bin/env python3
"""Stage-2 review state machine and new-topic review queue.

Pure standard library.  It does not import application code, does not connect to
MySQL/ChromaDB and does not write anywhere except an explicit ``--out-dir``.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE_DIR,
    PrototypeError,
    load_internal_snapshot,
    load_source,
    read_json,
    write_json,
    write_text,
)

REVIEW_STATES = (
    "pending_review",
    "confirmed",
    "rejected",
    "needs_split",
    "needs_merge",
    "new_topic_pending",
)
HIGH_RISK_PAIRS = {
    ("cnm_093", 10),
    ("cnm_200", 19),
    ("cnm_208", 10),
}

# Explicit transitions.  "undo" and "reopen" are the only ways back from a
# decision, and both keep the full history.
_TRANSITIONS = {
    "pending_review": {"confirmed", "rejected", "needs_split", "needs_merge"},
    "new_topic_pending": {"confirmed", "rejected", "needs_split", "needs_merge"},
    "needs_split": {"pending_review", "rejected", "confirmed"},
    "needs_merge": {"pending_review", "rejected", "confirmed"},
    "confirmed": {"pending_review"},
    "rejected": {"pending_review"},
}

_ACTIONS = {
    "confirm": "confirmed",
    "reject": "rejected",
    "split": "needs_split",
    "merge": "needs_merge",
    "new_topic": "new_topic_pending",
    "undo": "pending_review",
    "reopen": "pending_review",
}


class ReviewError(ValueError):
    pass


class ReviewStore:
    """Append-only review records with a small, explicit state machine."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, int | None], dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []

    def start(
        self,
        *,
        entity_type: str,
        external_id: str,
        internal_id: int | None = None,
        status: str = "pending_review",
        high_risk: bool = False,
        reason: str = "",
    ) -> dict[str, Any]:
        if status not in REVIEW_STATES:
            raise ReviewError(f"unknown status: {status}")
        key = (entity_type, external_id, internal_id)
        if key in self.records:
            raise ReviewError(f"review already exists: {key}")
        record = {
            "entity_type": entity_type,
            "external_id": external_id,
            "internal_id": internal_id,
            "status": status,
            "high_risk": high_risk,
            "reason": reason,
            "reviewer": None,
            "reviewed_at": None,
            "comment": "",
            "revision": 1,
            "history": [
                {
                    "revision": 1,
                    "status": status,
                    "action": "create",
                    "reviewer": None,
                    "comment": "",
                }
            ],
        }
        self.records[key] = record
        return record

    def apply(
        self,
        *,
        entity_type: str,
        external_id: str,
        internal_id: int | None,
        action: str,
        reviewer: str,
        comment: str = "",
        acknowledge_high_risk: bool = False,
    ) -> dict[str, Any]:
        key = (entity_type, external_id, internal_id)
        record = self.records.get(key)
        if record is None:
            raise ReviewError(f"unknown review: {key}")
        if action not in _ACTIONS:
            raise ReviewError(f"unknown action: {action}")
        target = _ACTIONS[action]
        current = record["status"]
        if target not in _TRANSITIONS.get(current, set()):
            raise ReviewError(f"invalid transition: {current} -> {target}")
        if not reviewer:
            raise ReviewError("reviewer is required")
        if record["high_risk"] and action == "confirm" and not acknowledge_high_risk:
            raise ReviewError("high-risk candidate requires explicit acknowledge_high_risk")
        if record["high_risk"] and action == "confirm" and not comment.strip():
            raise ReviewError("high-risk confirmation requires a comment")

        record["revision"] += 1
        record["status"] = target
        record["reviewer"] = reviewer
        record["reviewed_at"] = f"revision-{record['revision']}"
        record["comment"] = comment
        entry = {
            "revision": record["revision"],
            "status": target,
            "action": action,
            "reviewer": reviewer,
            "comment": comment,
            "acknowledge_high_risk": bool(acknowledge_high_risk),
        }
        record["history"].append(entry)
        self.history.append(
            {
                "entity_type": entity_type,
                "external_id": external_id,
                "internal_id": internal_id,
                **entry,
            }
        )
        return record

    def confirmed_pairs(self) -> set[tuple[str, int]]:
        return {
            (record["external_id"], record["internal_id"])
            for record in self.records.values()
            if record["status"] == "confirmed" and record["internal_id"] is not None
        }

    def rejected_pairs(self) -> set[tuple[str, int]]:
        return {
            (record["external_id"], record["internal_id"])
            for record in self.records.values()
            if record["status"] == "rejected" and record["internal_id"] is not None
        }

    def status_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(record["status"] for record in self.records.values()).items()))


def build_review_store(mapping: dict[str, Any]) -> ReviewStore:
    store = ReviewStore()
    for row in mapping["external_topics"]:
        if not row.get("candidates"):
            store.start(
                entity_type="new_topic",
                external_id=row["external_id"],
                internal_id=None,
                status="new_topic_pending",
                high_risk=False,
                reason=row.get("reason", ""),
            )
            continue
        for candidate in row["candidates"]:
            key = (row["external_id"], candidate["internal_id"])
            store.start(
                entity_type="mapping",
                external_id=row["external_id"],
                internal_id=candidate["internal_id"],
                status="pending_review",
                high_risk=bool(candidate.get("high_risk")) or key in HIGH_RISK_PAIRS,
                reason=candidate.get("reason", ""),
            )
    return store


def _internal_lookup(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    from common import normalize_name

    lookup: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot["knowledge_points"]:
        if row.get("parent_id") is None:
            continue
        lookup.setdefault(normalize_name(row["name"]), []).append(row)
    return lookup


def build_new_topic_queue(
    mapping: dict[str, Any], snapshot: dict[str, Any], source_dir: Path
) -> list[dict[str, Any]]:
    """Build the 303-node new-topic review queue with duplicate/ancestor checks."""
    from common import bigram_jaccard, normalize_name

    source = load_source(source_dir)
    topic_by_id = source["topic_by_id"]
    standards_by_id = {item["id"]: item for item in source["stage4_standards"]}
    internal = _internal_lookup(snapshot)
    internal_rows = [row for row in snapshot["knowledge_points"] if row.get("parent_id") is not None]

    queue: list[dict[str, Any]] = []
    for row in mapping["external_topics"]:
        if row.get("candidates"):
            continue
        external = topic_by_id.get(row["external_id"], {})
        norm = normalize_name(external.get("name", ""))
        candidates: list[dict[str, Any]] = []
        for internal_row in internal_rows:
            similarity = bigram_jaccard(external.get("name", ""), internal_row["name"])
            if internal_row["name"] == external.get("name") or similarity >= 0.6:
                candidates.append(
                    {
                        "internal_id": internal_row["internal_id"],
                        "internal_name": internal_row["name"],
                        "internal_path": internal_row["parent_path"],
                        "similarity": round(similarity, 3),
                        "relation": "same_name" if internal_row["name"] == external.get("name") else "near_name",
                    }
                )
        candidates.sort(key=lambda item: (-item["similarity"], item["internal_id"]))
        standards = [
            {
                "id": ref.get("id"),
                "confidence": ref.get("confidence"),
                "domain": (standards_by_id.get(ref.get("id")) or {}).get("domain"),
            }
            for ref in external.get("standards") or []
        ]
        prerequisites = [
            edge
            for edge in source["internal_edges"]
            if edge["topicId"] == row["external_id"]
        ]
        queue.append(
            {
                "external_id": row["external_id"],
                "name": row["external_name"],
                "external_path": " > ".join(
                    value for value in (external.get("domain"), external.get("chapter"), external.get("name")) if value
                ),
                "grade": external.get("grade"),
                "semester": external.get("semester"),
                "chapter": external.get("chapter"),
                "domain": external.get("domain"),
                "standards": standards,
                "prerequisites": [
                    {
                        "prerequisite_external_id": edge["prerequisiteId"],
                        "strength": edge.get("strength"),
                        "reason": edge.get("reason"),
                    }
                    for edge in prerequisites
                ],
                "duplicate_checks": candidates[:5],
                "duplicate_risk": "high" if any(item["similarity"] >= 0.8 for item in candidates) else (
                    "medium" if candidates else "none"
                ),
                "suggested_action": "review_existing" if candidates else "review_new",
                "review_status": "new_topic_pending",
                "review_comment": "",
            }
        )
    queue.sort(key=lambda item: item["external_id"])
    return queue


def _review_markdown(store: ReviewStore, queue: list[dict[str, Any]]) -> str:
    counts = store.status_counts()
    lines = [
        "# 10 人工映射审核机制（原型验证）",
        "",
        "> 状态标记：**new**。所有候选默认 `pending_review`，`confirmed=0`。",
        "",
        "## 审核状态机",
        "",
        "| 状态 | 允许动作 |",
        "|---|---|",
        "| `pending_review` | confirm / reject / split / merge |",
        "| `new_topic_pending` | confirm / reject / split / merge |",
        "| `needs_split` / `needs_merge` | 回到 pending / reject / confirm |",
        "| `confirmed` | undo（记录历史） |",
        "| `rejected` | reopen（保留拒绝记录） |",
        "",
        "高风险候选：`confirm` 必须显式 `acknowledge_high_risk=True` 且填写审核意见；自动/静默确认会被拒绝。",
        "",
        "## 当前分布",
        "",
        "| 状态 | 数量 |",
        "|---|---:|",
    ]
    for status in REVIEW_STATES:
        lines.append(f"| {status} | {counts.get(status, 0)} |")
    lines.extend(
        [
            "",
            f"- 映射候选记录：{sum(1 for r in store.records.values() if r['entity_type'] == 'mapping')}",
            f"- 无候选节点记录：{len(queue)}",
            "",
            "## 高风险候选（禁止自动确认）",
            "",
            "| external_id | internal_id | 状态 |",
            "|---|---:|---|",
        ]
    )
    for record in store.records.values():
        if record["high_risk"]:
            lines.append(
                f"| `{record['external_id']}` | {record['internal_id']} | {record['status']} |"
            )
    lines.extend(
        [
            "",
            "## 审核记录字段",
            "",
            "- 候选/外部/内部详情、册次、章节、匹配类型、相似度、理由、风险标记；",
            "- 审核状态、审核人、审核时间、审核意见、revision、完整 history；",
            "- 拒绝记录保留，重新推荐时默认跳过；撤销（undo）保留历史。",
            "",
        ]
    )
    return "\n".join(lines)


def _new_topic_markdown(queue: list[dict[str, Any]]) -> str:
    risky = [item for item in queue if item["duplicate_risk"] in {"high", "medium"}]
    lines = [
        "# 11 无候选节点新增审核（原型验证）",
        "",
        "> 状态标记：**new**。303 个无候选节点全部进入 `new_topic_pending`，未创建任何知识点。",
        "",
        f"- 队列总数：{len(queue)}",
        f"- 存在同名/近名内部知识点（需优先审核）：{len(risky)}",
        f"- 其余建议按新增流程审核：{len(queue) - len(risky)}",
        "",
        "## 重复/上下位检查结果（前 30 条）",
        "",
        "| external_id | name | risk | 近名内部候选 | 建议动作 |",
        "|---|---|---|---|---|",
    ]
    for item in risky[:30]:
        candidates = ", ".join(
            f"{row['internal_id']}:{row['internal_name']}({row['similarity']})"
            for row in item["duplicate_checks"][:3]
        )
        lines.append(
            f"| `{item['external_id']}` | {item['name']} | {item['duplicate_risk']} | "
            f"{candidates} | {item['suggested_action']} |"
        )
    lines.extend(
        [
            "",
            "## 新增前检查",
            "",
            "1. 内部同义/近义检查（字符 bigram ≥ 0.6 或同名）；",
            "2. 上下位关系检查（同章/同 domain，建议人工确认父节点）；",
            "3. 目录结构判定（`suggested_action=review_existing` 时优先复用语内节点）；",
            "4. 重复检查（同名/近名候选列表）；",
            "5. 拆分/合并检查（由审核人标记 `needs_split` / `needs_merge`）；",
            "",
            "新增知识点必须人工确认；原型只登记审核队列，不批量创建。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--internal-snapshot", type=Path, default=None)
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    snapshot_path = args.internal_snapshot or (args.out_dir / "internal_snapshot.json")
    mapping_path = args.mapping or (args.out_dir / "mapping_result.json")
    try:
        snapshot = load_internal_snapshot(snapshot_path)
        mapping = read_json(mapping_path, label="mapping_result.json")
        if not isinstance(mapping, dict):
            raise PrototypeError("mapping_result.json must be an object")
        store = build_review_store(mapping)
        queue = build_new_topic_queue(mapping, snapshot, args.source_dir)
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "states": list(REVIEW_STATES),
        "status_counts": store.status_counts(),
        "records": [
            {
                key: value
                for key, value in record.items()
                if key != "history"
            }
            for record in store.records.values()
        ],
        "history": store.history,
        "new_topic_queue": queue,
        "high_risk_pairs": sorted([list(item) for item in HIGH_RISK_PAIRS]),
    }
    write_json(args.out_dir / "stage2_review.json", payload)
    write_text(args.out_dir / "10_mapping_review_workflow.md", _review_markdown(store, queue))
    write_text(args.out_dir / "11_new_topic_review.md", _new_topic_markdown(queue))
    print(
        "review state machine written: "
        f"records={len(store.records)} new_topics={len(queue)} "
        f"high_risk={sum(1 for r in store.records.values() if r['high_risk'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
