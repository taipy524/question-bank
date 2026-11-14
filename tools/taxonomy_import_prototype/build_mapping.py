#!/usr/bin/env python3
"""Build deterministic candidate mappings between the external taxonomy and the
existing internal knowledge points.

Rules (no AI, no ChromaDB, no database access):

* ``exact``: normalised names are identical.  A path/domain mismatch is kept but
  flagged as ``conflict`` instead of being silently accepted.
* ``semantic``: only when the external domain family matches the internal top
  category family and the character-bigram Jaccard similarity is >= 0.6.
* Cardinality is derived from the deduplicated candidate graph, so a component is
  counted exactly once (1-1 / 1-N / N-1 / N-M).
* Every result stays ``pending_review``; confidence is ``null`` when a rule gives
  no basis.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CATEGORY_DOMAIN_FAMILY,
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE_DIR,
    EXACT_CONFLICT_CONFIDENCE,
    EXACT_CONFIDENCE,
    INTERNAL_DUPLICATE_THRESHOLD,
    SEMANTIC_JACCARD_THRESHOLD,
    SOURCE_COMMIT,
    SOURCE_LICENSE_STATUS,
    SPLIT_MIN_EXTERNALS,
    PrototypeError,
    bigram_jaccard,
    ensure_dir,
    internal_category_name,
    internal_levels,
    load_internal_snapshot,
    load_source,
    normalize_name,
    write_csv,
    write_json,
    write_text,
)

CSV_FIELDS = [
    "external_id",
    "external_name",
    "external_domain",
    "external_grade",
    "external_semester",
    "external_chapter",
    "internal_id",
    "internal_name",
    "internal_parent_path",
    "match_type",
    "evidence",
    "similarity",
    "confidence",
    "reason",
    "conflict",
    "risk",
    "high_risk",
    "review_status",
    "component_id",
    "component_shape",
]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, node: str) -> None:
        self.parent.setdefault(node, node)

    def find(self, node: str) -> str:
        root = node
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[node] != root:
            self.parent[node], node = root, self.parent[node]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _internal_context(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[int, str]]:
    rows = snapshot["knowledge_points"]
    by_id = {row["internal_id"]: row for row in rows}
    levels = internal_levels(snapshot)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        category = internal_category_name(row, by_id)
        enriched.append(
            {
                **row,
                "level": levels[row["internal_id"]],
                "category": category,
                "family": CATEGORY_DOMAIN_FAMILY.get(category) if category else None,
                "normalized": normalize_name(row["name"]),
            }
        )
    return enriched, by_id, levels


def _candidate_pairs(
    external_topics: list[dict[str, Any]], internals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    mappable = [row for row in internals if row["level"] != "structural"]
    pairs: list[dict[str, Any]] = []

    for external in external_topics:
        external_norm = normalize_name(external["name"])
        domain = external.get("domain")
        exact = [row for row in mappable if row["normalized"] == external_norm]
        if exact:
            selected = [(row, "exact", 1.0) for row in exact]
        else:
            selected = []
            for row in mappable:
                if row["family"] != domain:
                    continue
                similarity = bigram_jaccard(external["name"], row["name"])
                if similarity >= SEMANTIC_JACCARD_THRESHOLD:
                    selected.append((row, "semantic", round(similarity, 3)))
            selected.sort(key=lambda item: (-item[2], item[0]["internal_id"]))

        for row, evidence, similarity in selected:
            conflict = evidence == "exact" and row["family"] is not None and row["family"] != domain
            if evidence == "exact":
                confidence: float | None = (
                    EXACT_CONFLICT_CONFIDENCE if conflict else EXACT_CONFIDENCE
                )
                if conflict:
                    reason = (
                        f"exact_name_match; domain_conflict external={domain} "
                        f"internal_family={row['family']}; path={row['parent_path']}"
                    )
                else:
                    reason = f"exact_name_match; domain={domain}; path={row['parent_path']}"
            else:
                confidence = similarity
                reason = (
                    f"semantic_bigram_jaccard={similarity:.3f} "
                    f"(threshold {SEMANTIC_JACCARD_THRESHOLD}); domain={domain}; "
                    f"path={row['parent_path']}"
                )
            risk = None
            high_risk = False
            if evidence == "semantic":
                risk = _high_risk_reason(external["name"], row["name"])
                if risk is not None:
                    high_risk = True
                elif _single_char_difference(external["name"], row["name"]):
                    risk = "single_char_difference"
            pairs.append(
                {
                    "risk": risk,
                    "high_risk": high_risk,
                    "external_id": external["id"],
                    "external_name": external["name"],
                    "external_domain": domain,
                    "external_grade": external.get("grade"),
                    "external_semester": external.get("semester"),
                    "external_chapter": external.get("chapter"),
                    "internal_id": row["internal_id"],
                    "internal_name": row["name"],
                    "internal_parent_path": row["parent_path"],
                    "evidence": evidence,
                    "similarity": similarity,
                    "confidence": confidence,
                    "reason": reason,
                    "conflict": bool(conflict),
                    "review_status": "pending_review",
                }
            )
    # Deduplicate pairs, preferring exact evidence and then the highest score.
    best: dict[tuple[str, int], dict[str, Any]] = {}
    for pair in pairs:
        key = (pair["external_id"], pair["internal_id"])
        current = best.get(key)
        if current is None or _pair_rank(pair) > _pair_rank(current):
            best[key] = pair
    unique = sorted(best.values(), key=lambda item: (item["external_id"], item["internal_id"]))
    return unique


def _single_char_difference(left: str, right: str) -> bool:
    left_norm, right_norm = normalize_name(left), normalize_name(right)
    if len(left_norm) != len(right_norm):
        return False
    return sum(a != b for a, b in zip(left_norm, right_norm)) == 1


# Characters whose substitution in an otherwise identical name commonly changes
# the mathematical meaning (正/反, 三/二, 一/二, 增/减 …).  These are not used to
# "confirm" anything; they only raise a high-risk review flag.
_CONFUSABLE_PAIRS = {
    frozenset(pair)
    for pair in (
        ("正", "反"), ("正", "负"),
        ("一", "二"), ("二", "三"), ("三", "四"),
        ("上", "下"), ("增", "减"), ("加", "减"),
        ("大", "小"), ("内", "外"), ("多", "少"),
        ("直", "曲"), ("锐", "钝"),
    )
}
_CONCEPT_MARKERS = (
    "函数", "方程", "不等式", "三角形", "图形", "圆", "统计", "概率",
    "坐标", "几何", "代数", "数列", "向量", "集合",
)
_COMPOSITE_SEPARATORS = ("与", "和", "及")


def _confusable_substitution(left: str, right: str) -> str | None:
    left_norm, right_norm = normalize_name(left), normalize_name(right)
    if len(left_norm) != len(right_norm):
        return None
    diffs = [(a, b) for a, b in zip(left_norm, right_norm) if a != b]
    if len(diffs) != 1:
        return None
    pair = frozenset(diffs[0])
    if pair in _CONFUSABLE_PAIRS:
        return f"confusable_single_char:{diffs[0][0]}->{diffs[0][1]}"
    return None


def _composite_other_concept(external_name: str, internal_name: str) -> str | None:
    """External name embeds the internal name plus another concept (e.g. 一次函数与二元一次方程组)."""
    external_norm = normalize_name(external_name)
    internal_norm = normalize_name(internal_name)
    if not internal_norm or internal_norm == external_norm or internal_norm not in external_norm:
        return None
    extra = external_norm.replace(internal_norm, "", 1)
    has_separator = any(separator in extra for separator in _COMPOSITE_SEPARATORS)
    has_concept = any(marker in extra for marker in _CONCEPT_MARKERS)
    if has_separator and has_concept:
        return "composite_topic_contains_other_concept"
    return None


def _high_risk_reason(external_name: str, internal_name: str) -> str | None:
    """Deterministic high-risk flags, independent of the equal-length heuristic."""
    return _confusable_substitution(external_name, internal_name) or _composite_other_concept(
        external_name, internal_name
    )


def _pair_rank(pair: dict[str, Any]) -> tuple[int, float]:
    return (1 if pair["evidence"] == "exact" else 0, float(pair["similarity"]))


def _components(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    union = _UnionFind()
    for pair in pairs:
        union.add(f"e:{pair['external_id']}")
        union.add(f"i:{pair['internal_id']}")
        union.union(f"e:{pair['external_id']}", f"i:{pair['internal_id']}")

    groups: dict[str, dict[str, set[str]]] = {}
    for pair in pairs:
        root = union.find(f"e:{pair['external_id']}")
        group = groups.setdefault(root, {"externals": set(), "internals": set()})
        group["externals"].add(pair["external_id"])
        group["internals"].add(str(pair["internal_id"]))

    components: list[dict[str, Any]] = []
    for group in groups.values():
        externals = sorted(group["externals"])
        internals = sorted(group["internals"], key=int)
        if len(externals) == 1 and len(internals) == 1:
            shape = "1-1"
        elif len(internals) == 1:
            shape = "1-N"
        elif len(externals) == 1:
            shape = "N-1"
        else:
            shape = "N-M"
        components.append(
            {
                "component_id": "",
                "shape": shape,
                "externals": externals,
                "internals": [int(value) for value in internals],
            }
        )
    components.sort(key=lambda item: (item["externals"][0], item["shape"]))
    for index, component in enumerate(components, start=1):
        component["component_id"] = f"C{index:04d}"
    return components


def _primary_internal(pairs: list[dict[str, Any]]) -> int:
    ordered = sorted(pairs, key=lambda item: (-_pair_rank(item)[0], -_pair_rank(item)[1], item["internal_id"]))
    return ordered[0]["internal_id"]


def _internal_duplicates(internals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for row in internals if row["level"] != "structural"]
    by_id = {row["internal_id"]: row for row in rows}
    findings: list[dict[str, Any]] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            if _is_ancestor(left, right, by_id) or _is_ancestor(right, left, by_id):
                continue
            similarity = bigram_jaccard(left["name"], right["name"])
            if left["normalized"] != right["normalized"] and similarity < INTERNAL_DUPLICATE_THRESHOLD:
                continue
            findings.append(
                {
                    "left_id": left["internal_id"],
                    "left_name": left["name"],
                    "left_path": left["parent_path"],
                    "right_id": right["internal_id"],
                    "right_name": right["name"],
                    "right_path": right["parent_path"],
                    "similarity": round(similarity, 3),
                    "reason": "same_normalized_name" if left["normalized"] == right["normalized"] else "high_bigram_similarity",
                }
            )
    findings.sort(key=lambda item: (item["left_id"], item["right_id"]))
    return findings


def _is_ancestor(
    ancestor: dict[str, Any], node: dict[str, Any], by_id: dict[int, dict[str, Any]]
) -> bool:
    cursor = node.get("parent_id")
    seen: set[int] = set()
    while cursor is not None:
        if cursor == ancestor["internal_id"]:
            return True
        if cursor in seen:
            return False
        seen.add(cursor)
        parent = by_id.get(cursor)
        if parent is None:
            return False
        cursor = parent.get("parent_id")
    return False


def build_mapping(
    source_dir: Path, snapshot: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = load_source(source_dir)
    internals, _, _ = _internal_context(snapshot)
    pairs = _candidate_pairs(source["junior_topics"], internals)
    components = _components(pairs)

    component_by_external: dict[str, dict[str, Any]] = {}
    for component in components:
        for external_id in component["externals"]:
            component_by_external[external_id] = component

    pairs_by_external: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        pairs_by_external.setdefault(pair["external_id"], []).append(pair)

    external_rows: list[dict[str, Any]] = []
    for external in source["junior_topics"]:
        external_pairs = pairs_by_external.get(external["id"], [])
        component = component_by_external.get(external["id"])
        if not external_pairs:
            match_type = "new_topic"
            shape = None
            component_id = None
            best_internal = None
            confidence = None
            reason = "no_candidate (exact/semantic thresholds not met)"
            suggestion_internal = None
            high_risk_only = False
        else:
            assert component is not None
            shape = component["shape"]
            component_id = component["component_id"]
            ordered_pairs = sorted(
                external_pairs,
                key=lambda item: (-_pair_rank(item)[0], -_pair_rank(item)[1], item["internal_id"]),
            )
            best_pair = ordered_pairs[0]
            best_internal = best_pair["internal_id"]
            confidence = best_pair["confidence"]
            reason = best_pair["reason"]
            if shape == "1-1":
                match_type = best_pair["evidence"]
            elif shape == "1-N":
                match_type = "one_to_many"
            elif shape == "N-1":
                match_type = "many_to_one"
            else:
                match_type = "many_to_many"

        safe_pairs = [pair for pair in external_pairs if not pair.get("high_risk")]
        suggestion_pair = sorted(
            safe_pairs,
            key=lambda item: (-_pair_rank(item)[0], -_pair_rank(item)[1], item["internal_id"]),
        )[0] if safe_pairs else None

        external_rows.append(
            {
                "external_id": external["id"],
                "external_name": external["name"],
                "external_domain": external.get("domain"),
                "external_grade": external.get("grade"),
                "external_semester": external.get("semester"),
                "external_chapter": external.get("chapter"),
                "match_type": match_type,
                "confidence": confidence,
                "reason": reason,
                "review_status": "pending_review",
                "component_id": component_id,
                "component_shape": shape,
                "best_internal_id": best_internal,
                "suggestion_internal_id": suggestion_pair["internal_id"] if suggestion_pair else None,
                "high_risk": bool(external_pairs) and not safe_pairs,
                "candidates": external_pairs,
            }
        )

    matched_internal_ids = {pair["internal_id"] for pair in pairs}
    internal_unmatched = [
        {
            "internal_id": row["internal_id"],
            "internal_name": row["name"],
            "internal_parent_path": row["parent_path"],
            "level": row["level"],
        }
        for row in internals
        if row["level"] != "structural" and row["internal_id"] not in matched_internal_ids
    ]

    component_shapes: dict[str, int] = {"1-1": 0, "1-N": 0, "N-1": 0, "N-M": 0}
    for component in components:
        component_shapes[component["shape"]] += 1

    match_type_counts: dict[str, int] = {}
    for row in external_rows:
        match_type_counts[row["match_type"]] = match_type_counts.get(row["match_type"], 0) + 1

    exact_conflict_pairs = [pair for pair in pairs if pair["conflict"]]
    # Split suggestions intentionally ignore high-risk candidates: a coarse
    # internal node must not be recommended for splitting based on a known
    # 三元/二元 or 正/反 style false positive.
    safe_pairs = [pair for pair in pairs if not pair.get("high_risk")]
    safe_by_internal: dict[int, set[str]] = {}
    for pair in safe_pairs:
        safe_by_internal.setdefault(pair["internal_id"], set()).add(pair["external_id"])
    component_by_internal: dict[int, str] = {}
    for component in components:
        if len(component["internals"]) == 1:
            component_by_internal[component["internals"][0]] = component["component_id"]
    split_candidates = []
    for internal_id in sorted(safe_by_internal):
        external_ids = sorted(safe_by_internal[internal_id])
        if len(external_ids) < SPLIT_MIN_EXTERNALS:
            continue
        split_candidates.append(
            {
                "internal_id": internal_id,
                "component_id": component_by_internal.get(internal_id),
                "external_count": len(external_ids),
                "external_ids": external_ids,
                "distinct_chapters": sorted(
                    {
                        pair["external_chapter"]
                        for pair in safe_pairs
                        if pair["internal_id"] == internal_id
                    }
                ),
            }
        )
    merge_candidates = [
        {
            "component_id": component["component_id"],
            "external_id": component["externals"][0],
            "internal_ids": component["internals"],
        }
        for component in components
        if component["shape"] == "N-1"
    ]

    stats = {
        "external_total": len(source["junior_topics"]),
        "external_with_candidates": sum(1 for row in external_rows if row["candidates"]),
        "candidate_nodes": sum(1 for row in external_rows if row["candidates"]),
        "external_new_topic": match_type_counts.get("new_topic", 0),
        "no_candidate_nodes": match_type_counts.get("new_topic", 0),
        "suggestion_nodes": sum(1 for row in external_rows if row.get("suggestion_internal_id") is not None),
        "high_risk_nodes": sum(1 for row in external_rows if row.get("high_risk")),
        "pairs_total": len(pairs),
        "candidate_pairs": len(pairs),
        "high_risk_pairs": sum(1 for pair in pairs if pair.get("high_risk")),
        "confirmed_pairs": 0,
        "confirmed_projection_pairs": 0,
        "pairs_exact": sum(1 for pair in pairs if pair["evidence"] == "exact"),
        "pairs_semantic": sum(1 for pair in pairs if pair["evidence"] == "semantic"),
        "pairs_exact_conflict": len(exact_conflict_pairs),
        "pairs_semantic_risk": sum(1 for pair in pairs if pair.get("risk")),
        "name_conflict_externals": len({pair["external_id"] for pair in exact_conflict_pairs}),
        "components_total": len(components),
        "components_by_shape": component_shapes,
        "external_by_match_type": match_type_counts,
        "internal_total": len(internals),
        "internal_structural": sum(1 for row in internals if row["level"] == "structural"),
        "internal_mapped": len(matched_internal_ids),
        "internal_unmatched": len(internal_unmatched),
        "duplicate_internal_pairs": len(_internal_duplicates(internals)),
        "split_candidates": len(split_candidates),
        "merge_candidates": len(merge_candidates),
    }

    result = {
        "meta": {
            "source_repo": "https://github.com/xiaoyang111222/cn-math-taxonomy",
            "source_commit": SOURCE_COMMIT,
            "source_license_status": SOURCE_LICENSE_STATUS,
            "internal_snapshot": {
                "source": snapshot["meta"].get("source"),
                "exported_at": snapshot["meta"].get("exported_at"),
                "row_count": snapshot["meta"].get("row_count"),
                "snapshot_sha256": snapshot["meta"].get("snapshot_sha256"),
            },
            "rules": {
                "exact": "normalized name equality; path conflict flagged",
                "semantic": f"same domain family and bigram Jaccard >= {SEMANTIC_JACCARD_THRESHOLD}",
                "high_risk": "confusable single-character variant or composite topic embedding another concept",
                "review_status": "all pending_review",
                "new_topic": "no deterministic candidate; NOT a final add count",
            },
            "mode": "analysis_only",
            "projection_basis": "candidate_projection (no confirmed mappings)",
            "database_writes": 0,
        },
        "stats": stats,
        "external_topics": external_rows,
        "components": components,
        "internal_unmatched": internal_unmatched,
        "internal_not_applicable": [
            {
                "internal_id": row["internal_id"],
                "internal_name": row["name"],
                "reason": "structural_root (container node; not an external topic)",
            }
            for row in internals
            if row["level"] == "structural"
        ],
        "duplicate_internal_candidates": _internal_duplicates(internals),
        "split_candidates": split_candidates,
        "merge_candidates": merge_candidates,
        "high_risk_candidates": sorted(
            [pair for pair in pairs if pair.get("high_risk")],
            key=lambda item: (item["external_id"], item["internal_id"]),
        ),
        "name_conflicts": sorted(
            {
                (pair["external_id"], pair["internal_id"]): pair for pair in exact_conflict_pairs
            }.values(),
            key=lambda item: (item["external_id"], item["internal_id"]),
        ),
    }
    return result, internals


def _csv_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for topic in result["external_topics"]:
        if topic["candidates"]:
            for pair in topic["candidates"]:
                rows.append(
                    {
                        **pair,
                        "match_type": topic["match_type"],
                        "component_id": topic["component_id"],
                        "component_shape": topic["component_shape"],
                    }
                )
        else:
            rows.append(
                {
                    "external_id": topic["external_id"],
                    "external_name": topic["external_name"],
                    "external_domain": topic["external_domain"],
                    "external_grade": topic["external_grade"],
                    "external_semester": topic["external_semester"],
                    "external_chapter": topic["external_chapter"],
                    "match_type": topic["match_type"],
                    "confidence": "",
                    "reason": topic["reason"],
                    "review_status": topic["review_status"],
                }
            )
    rows.sort(key=lambda item: (item["external_id"], str(item.get("internal_id", ""))))
    return rows


def _markdown(result: dict[str, Any]) -> str:
    stats = result["stats"]
    shapes = stats["components_by_shape"]
    types = stats["external_by_match_type"]
    lines = [
        "# 03 映射报告（外部 315 → 内部 62）",
        "",
        "> 状态标记：**new**（复核修订版）。所有结果 `pending_review`；高风险候选不进入普通建议，未自动确认。",
        "",
        "## 方法与边界",
        "",
        f"- 外部数据：`{result['meta']['source_repo']}` @ `{SOURCE_COMMIT}`（许可证状态：{SOURCE_LICENSE_STATUS}）。",
        f"- 内部快照：`{result['meta']['internal_snapshot']['source']}`，导出时间 "
        f"`{result['meta']['internal_snapshot']['exported_at']}`，"
        f"{result['meta']['internal_snapshot']['row_count']} 行，SHA256 "
        f"`{result['meta']['internal_snapshot']['snapshot_sha256']}`。",
        "- 规则：exact = 规范化名称完全相同（路径冲突另标 conflict）；semantic = 同 domain 族且字符 bigram Jaccard ≥ 0.6。",
        "- 统计基于去重后的候选关系图；一个连通分量只计入一个基数类型。",
        "- 未调用 AI / ChromaDB / 数据库；本报告为只读分析。",
        "",
        "## 总体统计",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 外部知识点 | {stats['external_total']} |",
        f"| 有候选节点 | {stats['candidate_nodes']} |",
        f"| 无候选节点（new_topic，**不等于最终新增数量**） | {stats['no_candidate_nodes']} |",
        f"| 去重候选关系对 | {stats['candidate_pairs']} |",
        f"| exact 候选对 | {stats['pairs_exact']} |",
        f"| semantic 候选对 | {stats['pairs_semantic']} |",
        f"| 同名但路径/领域冲突对 | {stats['pairs_exact_conflict']} |",
        f"| 高风险候选对 | {stats['high_risk_pairs']} |",
        f"| 仅含高风险候选的节点 | {stats['high_risk_nodes']} |",
        f"| 可用于普通建议的节点 | {stats['suggestion_nodes']} |",
        f"| 已确认映射对 | {stats['confirmed_pairs']} |",
        f"| 连通分量 | {stats['components_total']} |",
        f"| 一对一分量 (1-1) | {shapes['1-1']} |",
        f"| 一对多分量 (1-N) | {shapes['1-N']} |",
        f"| 多对一分量 (N-1) | {shapes['N-1']} |",
        f"| 多对多分量 (N-M) | {shapes['N-M']} |",
        f"| 内部知识点（含根） | {stats['internal_total']} |",
        f"| 内部结构根节点（not_applicable） | {stats['internal_structural']} |",
        f"| 内部已匹配 | {stats['internal_mapped']} |",
        f"| 内部未匹配 | {stats['internal_unmatched']} |",
        f"| 内部疑似重复对 | {stats['duplicate_internal_pairs']} |",
        f"| 建议拆分 | {stats['split_candidates']} |",
        f"| 建议合并 | {stats['merge_candidates']} |",
        "",
        "外部节点 match_type 分布（按节点计，非分量计）：",
        "",
        "| match_type | 数量 | 说明 |",
        "|---|---:|---|",
    ]
    type_notes = {
        "new_topic": "无候选节点，不等于最终新增",
        "exact": "1-1 精确候选",
        "semantic": "1-1 语义候选",
        "one_to_many": "1-N 候选",
        "many_to_one": "N-1 候选",
        "many_to_many": "N-M 候选",
    }
    for key in sorted(types):
        lines.append(f"| {key} | {types[key]} | {type_notes.get(key, '')} |")
    lines.append("")
    lines.append("> 注意：`new_topic` 仅表示“没有确定性候选”，**不是**最终需要新增的数量；本阶段没有任何 `confirmed` 映射。")

    lines.extend(["", "## 同名但路径/领域冲突", ""])
    if result["name_conflicts"]:
        lines.append("| external_id | external_name | internal_id | internal_name | reason |")
        lines.append("|---|---|---:|---|---|")
        for pair in result["name_conflicts"]:
            lines.append(
                f"| {pair['external_id']} | {pair['external_name']} | {pair['internal_id']} "
                f"| {pair['internal_name']} | {pair['reason']} |"
            )
    else:
        lines.append("未发现同名但路径/领域冲突。")

    lines.extend(["", "## 高风险候选（不进入普通匹配建议）", ""])
    high_risk = result.get("high_risk_candidates") or []
    if high_risk:
        lines.append("| external_id | external_name | internal_id | internal_name | similarity | risk |")
        lines.append("|---|---|---:|---|---:|---|")
        for pair in high_risk:
            lines.append(
                f"| `{pair['external_id']}` | {pair['external_name']} | {pair['internal_id']} "
                f"| {pair['internal_name']} | {pair['similarity']} | {pair.get('risk') or ''} |"
            )
        lines.append(
            "\n这些候选存在语义反转/序列差异或复合主题嵌入，已被排除在普通匹配建议与拆分建议之外；"
            "必须人工裁决，不得自动确认。"
        )
    else:
        lines.append("无。")

    medium = sorted(
        {
            (pair["external_id"], pair["internal_id"]): pair
            for topic in result["external_topics"]
            for pair in topic["candidates"]
            if pair.get("risk") and not pair.get("high_risk")
        }.values(),
        key=lambda item: (item["external_id"], item["internal_id"]),
    )
    lines.extend(["", "## 其他字面接近风险", ""])
    if medium:
        lines.append("| external_id | external_name | internal_id | internal_name | similarity | risk |")
        lines.append("|---|---|---:|---|---:|---|")
        for pair in medium:
            lines.append(
                f"| `{pair['external_id']}` | {pair['external_name']} | {pair['internal_id']} "
                f"| {pair['internal_name']} | {pair['similarity']} | {pair.get('risk') or ''} |"
            )
        lines.append("\n这些候选同样必须人工确认，不能自动视为同一知识点。")
    else:
        lines.append("无。")

    lines.extend(["", "## 无候选节点（new_topic，按 domain 汇总；不等于最终新增）", ""])
    new_topics = [row for row in result["external_topics"] if row["match_type"] == "new_topic"]
    if new_topics:
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for row in new_topics:
            by_domain.setdefault(row["external_domain"] or "<unknown>", []).append(row)
        lines.append("| domain | 数量 | 示例（external_id: name） |")
        lines.append("|---|---:|---|")
        for domain in sorted(by_domain):
            examples = ", ".join(
                f"`{row['external_id']}`: {row['external_name']}" for row in by_domain[domain][:5]
            )
            lines.append(f"| {domain} | {len(by_domain[domain])} | {examples} |")
    else:
        lines.append("无。")

    lines.extend(["", "## 一对多（内部粗粒度 → 多个外部节点）", ""])
    one_to_many = [c for c in result["components"] if c["shape"] == "1-N"]
    if one_to_many:
        lines.append("| component | internal_id | internal_name | 外部数量 |")
        lines.append("|---|---:|---|---:|")
        internal_name = {
            pair["internal_id"]: pair["internal_name"]
            for topic in result["external_topics"]
            for pair in topic["candidates"]
        }
        for component in one_to_many[:50]:
            internal_id = component["internals"][0]
            lines.append(
                f"| {component['component_id']} | {internal_id} | "
                f"{internal_name.get(internal_id, '')} | {len(component['externals'])} |"
            )
        if len(one_to_many) > 50:
            lines.append(f"\n仅展示前 50 个，完整明细见 `mapping_result.json`。")
    else:
        lines.append("无。")

    lines.extend(["", "## 多对一（多个内部节点 → 一个外部节点）", ""])
    if result["merge_candidates"]:
        lines.append("| component | external_id | internal_ids |")
        lines.append("|---|---|---|")
        for item in result["merge_candidates"]:
            lines.append(
                f"| {item['component_id']} | {item['external_id']} | "
                f"{', '.join(str(value) for value in item['internal_ids'])} |"
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 内部未匹配知识点（可能新增/保留独立节点）", ""])
    if result["internal_unmatched"]:
        lines.append("| internal_id | name | level | parent_path |")
        lines.append("|---:|---|---|---|")
        for row in result["internal_unmatched"]:
            lines.append(
                f"| {row['internal_id']} | {row['internal_name']} | {row['level']} | {row['internal_parent_path']} |"
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 内部疑似重复", ""])
    if result["duplicate_internal_candidates"]:
        lines.append("| left | right | similarity | reason |")
        lines.append("|---|---|---:|---|")
        for item in result["duplicate_internal_candidates"]:
            lines.append(
                f"| {item['left_id']} {item['left_name']} | {item['right_id']} {item['right_name']} "
                f"| {item['similarity']} | {item['reason']} |"
            )
    else:
        lines.append("未发现疑似重复。")

    lines.extend(["", "## 附录：315 个外部节点状态索引", ""])
    lines.append("| external_id | name | match_type | best_internal_id | high_risk | confidence | risk |")
    lines.append("|---|---|---|---:|---|---:|---|")
    for row in result["external_topics"]:
        risk = next(
            (
                candidate.get("risk")
                for candidate in row["candidates"]
                if candidate["internal_id"] == row["best_internal_id"]
            ),
            None,
        )
        confidence = "" if row["confidence"] is None else row["confidence"]
        best = "" if row["best_internal_id"] is None else row["best_internal_id"]
        lines.append(
            f"| `{row['external_id']}` | {row['external_name']} | {row['match_type']} | "
            f"{best} | {'yes' if row.get('high_risk') else ''} | {confidence} | {risk or ''} |"
        )
    lines.extend(
        [
            "",
            "## 说明与限制",
            "",
            "- `confidence` 仅表示规则证据强度，不代表人工确认；无依据时为 `null`。",
            "- 语义匹配只覆盖同 domain 族且 Jaccard ≥ 0.6 的保守候选，因此大量外部细粒度知识点会进入 `new_topic`。",
        "- `new_topic` 仅表示“没有确定性候选”，不代表一定需要新增；内部大类（category）也参与匹配，结构根节点不参与。",
        "- 单字差异（如 正比例/反比例、三元/二元）可能被语义规则命中，已单列风险，必须人工裁决。",
            "- 1-N / N-1 / N-M 的计数以去重候选图的连通分量为基础，避免重复计数；节点级分布见上表。",
            "- 完整候选明细见 `mapping_candidates.csv` 与 `mapping_result.json`。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument(
        "--internal-snapshot", type=Path, default=None, help="default: <out-dir>/internal_snapshot.json"
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    ensure_dir(args.out_dir)
    snapshot_path = args.internal_snapshot or (args.out_dir / "internal_snapshot.json")
    try:
        snapshot = load_internal_snapshot(snapshot_path)
        result, _ = build_mapping(args.source_dir, snapshot)
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write_json(args.out_dir / "mapping_result.json", result)
    write_csv(args.out_dir / "mapping_candidates.csv", _csv_rows(result), CSV_FIELDS)
    write_text(args.out_dir / "03_mapping_report.md", _markdown(result))
    print(
        "mapping written: "
        f"external={result['stats']['external_total']} "
        f"pairs={result['stats']['pairs_total']} "
        f"new={result['stats']['external_new_topic']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
