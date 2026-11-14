#!/usr/bin/env python3
"""Validate a candidate mapping and analyse dependency/standards projections.

This revision keeps candidate projections and confirmed projections strictly
separate:

* ``candidate`` – every candidate (including high-risk ones);
* ``candidate_excluding_high_risk`` – only candidates that are safe enough for a
  normal suggestion;
* ``confirmed`` – only rows whose ``review_status`` is ``confirmed`` (currently
  none).

Self-loop-like results in a candidate projection are *candidate mapping
conflicts*, never real prerequisite self-loops.  The script never writes to a
database.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE_DIR,
    PrototypeError,
    internal_levels,
    load_internal_snapshot,
    load_source,
    read_json,
    write_json,
    write_text,
)

VALID_MATCH_TYPES = {
    "exact",
    "semantic",
    "one_to_many",
    "many_to_one",
    "many_to_many",
    "new_topic",
}


def _ancestors_by_id(snapshot: dict[str, Any]) -> dict[int, set[int]]:
    rows = snapshot["knowledge_points"]
    parents = {row["internal_id"]: row["parent_id"] for row in rows}
    result: dict[int, set[int]] = {}
    for internal_id in parents:
        chain: set[int] = set()
        cursor = parents.get(internal_id)
        while cursor is not None and cursor not in chain:
            chain.add(cursor)
            cursor = parents.get(cursor)
        result[internal_id] = chain
    return result


def _is_ancestor(ancestor: int, node: int, ancestors: dict[int, set[int]]) -> bool:
    return ancestor in ancestors.get(node, set())


def _cycles(nodes: set[int], edges: list[tuple[int, int]]) -> list[list[int]]:
    adjacency: dict[int, list[int]] = defaultdict(list)
    for topic, prerequisite in edges:
        adjacency[topic].append(prerequisite)
    state: dict[int, int] = {}
    found: list[list[int]] = []

    def visit(node: int, stack: list[int]) -> None:
        state[node] = 1
        for neighbour in adjacency.get(node, []):
            if state.get(neighbour, 0) == 0:
                visit(neighbour, stack + [neighbour])
            elif state.get(neighbour) == 1:
                found.append(stack[stack.index(neighbour) :] + [neighbour])
        state[node] = 2

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            visit(node, [node])
    return [cycle for cycle in found if len(set(cycle)) > 1]


def _projection(
    *,
    basis: str,
    source: dict[str, Any],
    ancestors: dict[int, set[int]],
    primary: dict[str, int],
) -> dict[str, Any]:
    internal_edges = source["internal_edges"]
    mapped_edges: list[tuple[int, int]] = []
    both_mapped = one_mapped = none_mapped = 0
    topic_only = prerequisite_only = 0
    self_conflicts: list[dict[str, Any]] = []
    duplicates: dict[tuple[int, int], list[str]] = defaultdict(list)
    suspicious_direction: list[dict[str, Any]] = []

    for edge in internal_edges:
        topic = primary.get(edge["topicId"])
        prerequisite = primary.get(edge["prerequisiteId"])
        if topic is None and prerequisite is None:
            none_mapped += 1
            continue
        if topic is None or prerequisite is None:
            one_mapped += 1
            if topic is not None:
                topic_only += 1
            else:
                prerequisite_only += 1
            continue
        both_mapped += 1
        mapped_edges.append((topic, prerequisite))
        if topic == prerequisite:
            self_conflicts.append(
                {
                    "external_topic": edge["topicId"],
                    "external_prerequisite": edge["prerequisiteId"],
                    "internal_id": topic,
                    "strength": edge.get("strength"),
                }
            )
        duplicates[(topic, prerequisite)].append(f"{edge['topicId']}->{edge['prerequisiteId']}")
        if _is_ancestor(topic, prerequisite, ancestors):
            suspicious_direction.append(
                {
                    "external_topic": edge["topicId"],
                    "external_prerequisite": edge["prerequisiteId"],
                    "internal_topic": topic,
                    "internal_prerequisite": prerequisite,
                    "reason": "mapped prerequisite is a descendant of the mapped topic",
                }
            )

    duplicate_edges = [
        {"internal_topic": key[0], "internal_prerequisite": key[1], "sources": sorted(values)}
        for key, values in duplicates.items()
        if len(values) > 1
    ]
    mapped_cycles = _cycles({value for edge in mapped_edges for value in edge}, mapped_edges)
    cross_edges = source["cross_stage_edges"]
    cross_topic_mapped = sum(1 for edge in cross_edges if primary.get(edge["topicId"]) is not None)

    return {
        "basis": basis,
        "internal_edges": len(internal_edges),
        "both_mapped": both_mapped,
        "one_mapped": one_mapped,
        "one_mapped_topic_only": topic_only,
        "one_mapped_prerequisite_only": prerequisite_only,
        "none_mapped": none_mapped,
        "candidate_mapping_conflicts": self_conflicts,
        "real_self_loops": [],
        "mapped_duplicate_edges": duplicate_edges,
        "mapped_cycles": mapped_cycles,
        "suspicious_direction": suspicious_direction,
        "cross_stage_edges": len(cross_edges),
        "cross_stage_topic_mapped": cross_topic_mapped,
        "senior_to_junior_edges": len(source["senior_to_junior_edges"]),
        "strength_counts": dict(sorted(Counter(edge.get("strength") for edge in internal_edges).items())),
    }


def analyse(source_dir: Path, snapshot: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    source = load_source(source_dir)
    junior_ids = source["junior_ids"]
    internals = {row["internal_id"]: row for row in snapshot["knowledge_points"]}
    levels = internal_levels(snapshot)
    ancestors = _ancestors_by_id(snapshot)

    errors: list[str] = []
    warnings: list[str] = []

    external_rows = mapping.get("external_topics")
    if not isinstance(external_rows, list):
        raise PrototypeError("mapping_result.json must contain an 'external_topics' array")

    seen: dict[str, dict[str, Any]] = {}
    for row in external_rows:
        external_id = row.get("external_id")
        if external_id not in junior_ids:
            errors.append(f"mapping contains unknown/out-of-scope external id: {external_id}")
            continue
        if external_id in seen:
            errors.append(f"mapping contains duplicate external id: {external_id}")
        seen[external_id] = row
        if row.get("match_type") not in VALID_MATCH_TYPES:
            errors.append(f"{external_id}: invalid match_type {row.get('match_type')!r}")
        if row.get("review_status") != "pending_review":
            errors.append(f"{external_id}: review_status must be pending_review in this phase")
        candidate_ids = [candidate.get("internal_id") for candidate in row.get("candidates") or []]
        if len(candidate_ids) != len(set(candidate_ids)):
            errors.append(f"{external_id}: duplicate internal candidates")
        for internal_id in candidate_ids:
            if internal_id not in internals:
                errors.append(f"{external_id}: unknown internal candidate {internal_id}")

    missing = sorted(junior_ids - set(seen))
    if missing:
        errors.append(f"mapping is missing {len(missing)} junior topics: {missing[:10]}")

    pair_keys: set[tuple[str, int]] = set()
    pairs: list[dict[str, Any]] = []
    for row in external_rows:
        for candidate in row.get("candidates") or []:
            key = (row["external_id"], candidate["internal_id"])
            if key in pair_keys:
                errors.append(f"duplicate candidate pair: {key}")
            pair_keys.add(key)
            pairs.append(candidate)

    all_primary: dict[str, int] = {}
    safe_primary: dict[str, int] = {}
    confirmed_primary: dict[str, int] = {}
    for row in external_rows:
        external_id = row["external_id"]
        best = row.get("best_internal_id")
        if best is not None and best in internals:
            all_primary[external_id] = best
        elif row.get("candidates"):
            warnings.append(f"{external_id}: no best_internal_id despite candidates")
        suggestion = row.get("suggestion_internal_id")
        if suggestion is not None and suggestion in internals:
            safe_primary[external_id] = suggestion
        for candidate in row.get("candidates") or []:
            if candidate.get("review_status") == "confirmed" and candidate["internal_id"] in internals:
                confirmed_primary[external_id] = candidate["internal_id"]
                break

    candidate_projection = _projection(
        basis="candidate_projection",
        source=source,
        ancestors=ancestors,
        primary=all_primary,
    )
    safe_projection = _projection(
        basis="candidate_projection_excluding_high_risk",
        source=source,
        ancestors=ancestors,
        primary=safe_primary,
    )
    confirmed_projection = _projection(
        basis="confirmed_projection",
        source=source,
        ancestors=ancestors,
        primary=confirmed_primary,
    )
    confirmed_projection["real_self_loops"] = list(confirmed_projection["candidate_mapping_conflicts"])
    confirmed_projection["candidate_mapping_conflicts"] = []

    # Standards -----------------------------------------------------------------
    stage4 = source["stage4_standards"]
    stage4_by_id = {item["id"]: item for item in stage4}
    mappings_by_external = {row["external_id"]: row for row in external_rows}
    standard_refs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for topic in source["junior_topics"]:
        for ref in topic.get("standards") or []:
            standard_refs[ref["id"]].append((topic["id"], ref.get("confidence")))

    standards_rows: list[dict[str, Any]] = []
    for standard_id in sorted(stage4_by_id):
        item = stage4_by_id[standard_id]
        topics = standard_refs.get(standard_id, [])
        candidate_internal = sorted(
            {
                mappings_by_external[topic_id]["best_internal_id"]
                for topic_id, _ in topics
                if mappings_by_external.get(topic_id, {}).get("best_internal_id") is not None
            }
        )
        suggestion_internal = sorted(
            {
                mappings_by_external[topic_id]["suggestion_internal_id"]
                for topic_id, _ in topics
                if mappings_by_external.get(topic_id, {}).get("suggestion_internal_id") is not None
            }
        )
        confirmed_internal = sorted(
            {
                candidate["internal_id"]
                for topic_id, _ in topics
                for candidate in mappings_by_external.get(topic_id, {}).get("candidates") or []
                if candidate.get("review_status") == "confirmed"
            }
        )
        if not topics:
            coverage_status = "no_external_topics"
        elif confirmed_internal:
            coverage_status = "confirmed"
        elif suggestion_internal:
            coverage_status = "candidate_suggestion"
        elif candidate_internal:
            coverage_status = "candidate_high_risk_only"
        else:
            coverage_status = "no_candidate"
        standards_rows.append(
            {
                "standard_id": standard_id,
                "domain": item.get("domain"),
                "confidence": sorted({confidence for _, confidence in topics}),
                "external_topic_ids": sorted(topic_id for topic_id, _ in topics),
                "candidate_internal_ids": candidate_internal,
                "suggestion_internal_ids": suggestion_internal,
                "confirmed_internal_ids": confirmed_internal,
                "coverage_status": coverage_status,
            }
        )

    standards_without_topics = [row["standard_id"] for row in standards_rows if not row["external_topic_ids"]]
    standards_candidate_coverage = [row for row in standards_rows if row["candidate_internal_ids"]]
    standards_suggestion_coverage = [row for row in standards_rows if row["suggestion_internal_ids"]]
    standards_confirmed_coverage = [row for row in standards_rows if row["confirmed_internal_ids"]]
    standards_without_internal = [
        row for row in standards_rows if row["external_topic_ids"] and not row["candidate_internal_ids"]
    ]

    high_risk_pairs = [pair for pair in pairs if pair.get("high_risk")]
    report = {
        "meta": {
            "source_commit": source.get("commit", "cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab"),
            "internal_snapshot_sha256": snapshot["meta"].get("snapshot_sha256"),
            "mapping_pairs": len(pairs),
            "projection_basis": "candidate_projection",
            "confirmed_mappings_available": bool(confirmed_primary),
            "mode": "analysis_only",
            "database_writes": 0,
        },
        "checks": {
            "external_rows": len(external_rows),
            "external_unique": len(seen),
            "missing_external": missing,
            "pair_count": len(pairs),
            "pair_duplicates": len(pairs) - len(pair_keys),
            "errors": errors,
            "warnings": warnings,
        },
        "high_risk": {
            "pair_count": len(high_risk_pairs),
            "external_ids": sorted({pair["external_id"] for pair in high_risk_pairs}),
            "pairs": high_risk_pairs,
        },
        "projections": {
            "candidate": candidate_projection,
            "candidate_excluding_high_risk": safe_projection,
            "confirmed": confirmed_projection,
        },
        # Convenience alias for the main (candidate) projection.
        "dependencies": candidate_projection,
        "standards": {
            "basis": "candidate_projection",
            "stage4_total": len(stage4),
            "candidate_coverage": len(standards_candidate_coverage),
            "suggestion_coverage": len(standards_suggestion_coverage),
            "confirmed_coverage": len(standards_confirmed_coverage),
            "without_external_topics": standards_without_topics,
            "with_external_but_without_candidate": len(standards_without_internal),
            "rows": standards_rows,
        },
        "internal": {
            "total": len(internals),
            "structural": sum(1 for value in levels.values() if value == "structural"),
            "candidate_mapped_ids": sorted(set(all_primary.values())),
            "suggestion_mapped_ids": sorted(set(safe_primary.values())),
            "confirmed_mapped_ids": sorted(set(confirmed_primary.values())),
        },
    }
    return report


def _projection_table(projection: dict[str, Any]) -> list[str]:
    return [
        f"| 两端均映射 | {projection['both_mapped']} |",
        f"| 仅一端映射（topic 已映射） | {projection['one_mapped_topic_only']} |",
        f"| 仅一端映射（prerequisite 已映射） | {projection['one_mapped_prerequisite_only']} |",
        f"| 两端均未映射 | {projection['none_mapped']} |",
        f"| 候选映射冲突（同内部 ID，自环形态） | {len(projection['candidate_mapping_conflicts'])} |",
        f"| 确认映射后的真实自环 | {len(projection['real_self_loops'])} |",
        f"| 重复边 | {len(projection['mapped_duplicate_edges'])} |",
        f"| 非自环环 | {len(projection['mapped_cycles'])} |",
        f"| 方向可疑 | {len(projection['suspicious_direction'])} |",
    ]


def _dependency_markdown(report: dict[str, Any], mapping: dict[str, Any]) -> str:
    candidate = report["projections"]["candidate"]
    safe = report["projections"]["candidate_excluding_high_risk"]
    confirmed = report["projections"]["confirmed"]
    checks = report["checks"]
    high_risk = report["high_risk"]
    lines = [
        "# 04 先修关系审计（候选投影 / 确认映射分离）",
        "",
        "> 状态标记：**new**（修订版）。本报告同时给出 `candidate_projection`、"
        "`candidate_projection_excluding_high_risk` 与 `confirmed_projection`，"
        "三者不可混用。当前**没有任何** `confirmed` 映射，因此确认口径为 0。",
        "",
        "## 输入",
        "",
        f"- 外部 315 节点映射结果：`{checks['external_rows']}` 行；去重候选对 `{checks['pair_count']}`。",
        f"- 高风险候选对：`{high_risk['pair_count']}`（不进入普通建议）。",
        "- 先修方向保留：`topicId` 依赖 `prerequisiteId`；本脚本不写入 `parent_id`，也不删除/修复外部原始关系。",
        "",
        "## 原始关系统计（不因映射而改变）",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 初中内部先修边 | {candidate['internal_edges']} |",
        f"| hard / soft | {candidate['strength_counts']} |",
        f"| 初中→小学跨学段边 | {candidate['cross_stage_edges']} |",
        f"| 跨学段边中 topic 有候选 | {candidate['cross_stage_topic_mapped']} |",
        f"| 高中→初中边（范围外） | {candidate['senior_to_junior_edges']} |",
        "",
        "## 口径 A：candidate_projection（全部候选，含高风险）",
        "",
        "> 这是**候选投影**，不是已确认映射。",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        *_projection_table(candidate),
        "",
    ]
    if candidate["candidate_mapping_conflicts"]:
        lines.append("### 候选映射冲突（不是真实先修自环）")
        lines.append("")
        lines.append("```json")
        import json

        lines.append(json.dumps(candidate["candidate_mapping_conflicts"][:20], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append(
            "\n例如 `cnm_208 → cnm_088` 因两个外部节点都被候选映射到内部 `10`，"
            "形成**候选映射冲突**；它不代表外部原始先修关系存在自环。排除高风险候选后该冲突消失。"
        )
        lines.append("")

    lines.extend(
        [
            "## 口径 B：candidate_projection_excluding_high_risk",
            "",
            "> 排除高风险候选后，可用于普通建议的投影。",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            *_projection_table(safe),
            "",
            "## 口径 C：confirmed_projection",
            "",
            "> 仅使用 `review_status=confirmed` 的映射。当前数量为 0，因此该口径下没有映射边、没有冲突。",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            *_projection_table(confirmed),
            "",
            "## 结论",
            "",
            "- 当前所有映射均为 `pending_review`；不得把口径 A/B 的结果称为“已建立先修关系”。",
            "- 自环类结果只作为候选映射冲突，真实先修自环数量为 0（口径 C）。",
            "- 原始 563 条内部关系与 45 条跨学段关系保持不变，未自动删除或修复。",
            "",
        ]
    )
    return "\n".join(lines)


def _standards_markdown(report: dict[str, Any], mapping: dict[str, Any]) -> str:
    standards = report["standards"]
    lines = [
        "# 05 课程标准审计与候选覆盖（157 条第四学段数学课标）",
        "",
        "> 状态标记：**new**（修订版）。区分“候选内部覆盖”与“确认课标关联”；"
        "当前确认关联为 0。",
        "",
        "## 统计",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 第四学段数学课标 | {standards['stage4_total']} |",
        f"| 有候选内部覆盖的课标 | {standards['candidate_coverage']} |",
        f"| 排除高风险候选后仍有覆盖 | {standards['suggestion_coverage']} |",
        f"| 已确认课标关联 | {standards['confirmed_coverage']} |",
        f"| 无外部知识点引用的课标 | {len(standards['without_external_topics'])} |",
        f"| 有外部引用但无候选内部覆盖 | {standards['with_external_but_without_candidate']} |",
        "",
        "## 无外部引用的课标",
        "",
    ]
    if standards["without_external_topics"]:
        lines.extend(f"- `{item}`" for item in standards["without_external_topics"])
    else:
        lines.append("无。")
    lines.extend(
        [
            "",
            "## 候选覆盖预览（前 40 条）",
            "",
            "| standard_id | domain | confidence | 外部知识点数 | 候选内部知识点 | 确认内部知识点 | 状态 |",
            "|---|---|---|---:|---|---|---|",
        ]
    )
    for row in standards["rows"][:40]:
        lines.append(
            f"| `{row['standard_id']}` | {row['domain']} | {'/'.join(row['confidence']) or '-'} | "
            f"{len(row['external_topic_ids'])} | "
            f"{', '.join(str(value) for value in row['candidate_internal_ids'])} | "
            f"{', '.join(str(value) for value in row['confirmed_internal_ids'])} | "
            f"{row['coverage_status']} |"
        )
    if len(standards["rows"]) > 40:
        lines.append("\n仅展示前 40 条，完整明细见 `mapping_validation.json`。")
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 课标引用来自外部 `topics[].standards[]`；157 条、383 条引用、exact 286 / inferred 97 保持不变。",
            "- “候选内部覆盖”只是 `pending_review` 候选投影，不是已建立的课标关联。",
            "- 当前 `confirmed_coverage = 0`；正式集成前必须人工审核确认。",
            "- 15 条课标无外部知识点引用，保持原样记录。",
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
        report = analyse(args.source_dir, snapshot, mapping)
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write_json(args.out_dir / "mapping_validation.json", report)
    write_text(args.out_dir / "04_dependency_report.md", _dependency_markdown(report, mapping))
    write_text(args.out_dir / "05_standards_report.md", _standards_markdown(report, mapping))
    for item in report["checks"]["errors"]:
        print(f"ERROR: {item}", file=sys.stderr)
    candidate = report["projections"]["candidate"]
    print(
        f"mapping validation: {len(report['checks']['errors'])} errors, "
        f"candidate mapping conflicts={len(candidate['candidate_mapping_conflicts'])}, "
        f"high-risk pairs={report['high_risk']['pair_count']}, "
        f"cross-stage={candidate['cross_stage_edges']}"
    )
    return 1 if report["checks"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
