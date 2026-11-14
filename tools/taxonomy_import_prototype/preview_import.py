#!/usr/bin/env python3
"""Dry-run import preview.

Candidate suggestions and confirmed mappings are kept separate.  High-risk
candidates never appear in the normal suggestion list.  The script never opens a
database connection and never imports business code.
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
    load_source,
    read_json,
    write_json,
    write_text,
)


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = read_json(path, label=path.name)
    return payload if isinstance(payload, dict) else None


def build_preview(
    mapping: dict[str, Any],
    validation: dict[str, Any] | None,
    source_dir: Path,
) -> dict[str, Any]:
    source = load_source(source_dir)
    rows = mapping["external_topics"]
    stats = mapping["stats"]

    by_type = Counter(row["match_type"] for row in rows)
    high_risk_rows = [row for row in rows if row.get("high_risk")]
    suggestion_rows = [row for row in rows if row.get("suggestion_internal_id") is not None]
    direct = [
        row
        for row in rows
        if row.get("suggestion_internal_id") is not None
        and row["match_type"] in {"exact", "semantic"}
    ]
    no_candidate = [row for row in rows if not row.get("candidates")]
    confirmed_rows = [
        row
        for row in rows
        for candidate in row.get("candidates") or []
        if candidate.get("review_status") == "confirmed"
    ]

    projections = (validation or {}).get("projections", {})
    candidate_projection = projections.get("candidate", {})
    safe_projection = projections.get("candidate_excluding_high_risk", {})
    confirmed_projection = projections.get("confirmed", {})
    standards = (validation or {}).get("standards", {})

    risks: list[str] = []
    if stats.get("pairs_exact_conflict"):
        risks.append(f"存在 {stats['pairs_exact_conflict']} 对同名但路径/领域冲突，必须人工裁决。")
    if high_risk_rows:
        risks.append(f"{len(high_risk_rows)} 个节点仅含高风险候选，已从普通建议中排除。")
    if candidate_projection.get("candidate_mapping_conflicts"):
        risks.append(
            f"候选投影出现 {len(candidate_projection['candidate_mapping_conflicts'])} 条候选映射冲突（自环形态），"
            "不是真实先修自环；排除高风险候选后为 "
            f"{len(safe_projection.get('candidate_mapping_conflicts') or [])} 条。"
        )
    if confirmed_projection.get("real_self_loops"):
        risks.append(f"确认映射下存在 {len(confirmed_projection['real_self_loops'])} 条真实先修自环。")
    else:
        risks.append("当前没有 confirmed 映射，确认口径下真实先修自环为 0。")
    if stats.get("split_candidates"):
        risks.append(f"{stats['split_candidates']} 个内部知识点可能需拆分（已排除高风险候选）。")
    if stats.get("merge_candidates"):
        risks.append(f"{stats['merge_candidates']} 组内部知识点可能需合并。")
    if stats.get("duplicate_internal_pairs"):
        risks.append(f"内部疑似重复 {stats['duplicate_internal_pairs']} 对。")

    preview = {
        "meta": {
            "mode": "dry_run",
            "dry_run": True,
            "database_writes": 0,
            "external_commit": mapping["meta"].get("source_commit"),
            "internal_snapshot_sha256": mapping["meta"].get("internal_snapshot", {}).get("snapshot_sha256"),
            "review_policy": "all pending_review; nothing auto-confirmed",
            "confirmed_mappings_available": bool(confirmed_rows),
            "projection_basis": "candidate_projection",
        },
        "summary": {
            "external_total": stats.get("external_total"),
            "candidate_nodes": stats.get("candidate_nodes"),
            "no_candidate_nodes": stats.get("no_candidate_nodes"),
            "candidate_pairs": stats.get("candidate_pairs"),
            "high_risk_nodes": stats.get("high_risk_nodes"),
            "suggestion_nodes": len(suggestion_rows),
            "direct_suggestions": len(direct),
            "pending_review_nodes": len(suggestion_rows) + len(high_risk_rows),
            "confirmed_mappings": 0,
            "match_type_counts": dict(sorted(by_type.items())),
            "internal_total": stats.get("internal_total"),
            "internal_candidate_mapped": stats.get("internal_mapped"),
            "internal_unmatched": stats.get("internal_unmatched"),
            "dependencies_internal_edges": candidate_projection.get("internal_edges"),
            "dependencies_candidate_both_mapped": candidate_projection.get("both_mapped"),
            "dependencies_candidate_conflicts": len(
                candidate_projection.get("candidate_mapping_conflicts") or []
            ),
            "dependencies_confirmed_self_loops": len(
                confirmed_projection.get("real_self_loops") or []
            ),
            "standards_total": standards.get("stage4_total"),
            "standards_candidate_coverage": standards.get("candidate_coverage"),
            "standards_confirmed_coverage": standards.get("confirmed_coverage", 0),
        },
        "direct_suggestions": [
            {
                "external_id": row["external_id"],
                "external_name": row["external_name"],
                "internal_id": row["suggestion_internal_id"],
                "match_type": row["match_type"],
                "confidence": row["confidence"],
                "risk": next(
                    (
                        candidate.get("risk")
                        for candidate in row["candidates"]
                        if candidate["internal_id"] == row["suggestion_internal_id"]
                    ),
                    None,
                ),
                "review_status": row["review_status"],
            }
            for row in direct
        ],
        "high_risk_candidates": [
            {
                "external_id": row["external_id"],
                "external_name": row["external_name"],
                "internal_id": candidate["internal_id"],
                "internal_name": candidate["internal_name"],
                "risk": candidate.get("risk"),
                "reason": candidate.get("reason"),
            }
            for row in high_risk_rows
            for candidate in row.get("candidates") or []
            if candidate.get("high_risk")
        ],
        "no_candidate_nodes": [
            {
                "external_id": row["external_id"],
                "external_name": row["external_name"],
                "domain": row["external_domain"],
                "grade": row["external_grade"],
                "semester": row["external_semester"],
                "chapter": row["external_chapter"],
            }
            for row in no_candidate
        ],
        "risks": risks,
        "validation": {
            "mapping_errors": (validation or {}).get("checks", {}).get("errors", []),
            "mapping_warnings": (validation or {}).get("checks", {}).get("warnings", []),
        },
        "inputs": {
            "source_dir": str(source_dir),
            "source_topics": len(source["junior_topics"]),
        },
    }
    return preview


def _markdown(preview: dict[str, Any]) -> str:
    summary = preview["summary"]
    lines = [
        "# 06 导入预览（dry-run，不写入数据库）",
        "",
        "> 状态标记：**new**（修订版）。仅模拟候选结果；`database_writes = 0`，"
        "无 `confirmed` 映射，未调用 ChromaDB/AI。",
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 外部知识点 | {summary['external_total']} |",
        f"| 有候选节点 | {summary['candidate_nodes']} |",
        f"| 无候选节点（new_topic，不等于最终新增） | {summary['no_candidate_nodes']} |",
        f"| 去重候选关系对 | {summary['candidate_pairs']} |",
        f"| 高风险节点（仅高风险候选） | {summary['high_risk_nodes']} |",
        f"| 可进入普通建议的节点 | {summary['suggestion_nodes']} |",
        f"| 1-1 直接建议（exact/semantic） | {summary['direct_suggestions']} |",
        f"| 待人工审核节点 | {summary['pending_review_nodes']} |",
        f"| 已确认映射 | {summary['confirmed_mappings']} |",
        f"| 内部已匹配（候选口径） | {summary['internal_candidate_mapped']} |",
        f"| 内部未匹配 | {summary['internal_unmatched']} |",
        f"| 先修边（初中内部） | {summary['dependencies_internal_edges']} |",
        f"| 候选投影两端均映射 | {summary['dependencies_candidate_both_mapped']} |",
        f"| 候选映射冲突（非真实自环） | {summary['dependencies_candidate_conflicts']} |",
        f"| 确认口径真实自环 | {summary['dependencies_confirmed_self_loops']} |",
        f"| 第四学段课标 | {summary['standards_total']} |",
        f"| 课标存在候选内部覆盖 | {summary['standards_candidate_coverage']} |",
        f"| 课标已确认关联 | {summary['standards_confirmed_coverage']} |",
        "",
        "match_type 分布（按节点计）：",
        "",
        "| match_type | 数量 |",
        "|---|---:|",
    ]
    for key, value in summary["match_type_counts"].items():
        lines.append(f"| {key} | {value} |")

    lines.extend(["", "## 1-1 普通建议（仍需人工确认）", ""])
    if preview["direct_suggestions"]:
        lines.append("| external_id | external_name | internal_id | type | confidence | risk |")
        lines.append("|---|---|---:|---|---:|---|")
        for row in preview["direct_suggestions"][:50]:
            lines.append(
                f"| `{row['external_id']}` | {row['external_name']} | {row['internal_id']} | "
                f"{row['match_type']} | {row['confidence']} | {row['risk'] or '-'} |"
            )
        if len(preview["direct_suggestions"]) > 50:
            lines.append("\n仅展示前 50 条，完整明细见 `import_preview.json`。")
    else:
        lines.append("无。")

    lines.extend(["", "## 高风险候选（不得进入普通建议，不得自动确认）", ""])
    if preview["high_risk_candidates"]:
        lines.append("| external_id | external_name | internal_id | internal_name | risk |")
        lines.append("|---|---|---:|---|---|")
        for row in preview["high_risk_candidates"]:
            lines.append(
                f"| `{row['external_id']}` | {row['external_name']} | {row['internal_id']} | "
                f"{row['internal_name']} | {row['risk']} |"
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 无候选节点（按 domain；不等于最终新增）", ""])
    if preview["no_candidate_nodes"]:
        counter = Counter(row["domain"] for row in preview["no_candidate_nodes"])
        lines.append("| domain | 数量 |")
        lines.append("|---|---:|")
        for key in sorted(counter, key=str):
            lines.append(f"| {key} | {counter[key]} |")
    else:
        lines.append("无。")

    lines.extend(["", "## 冲突与风险", ""])
    lines.extend([f"- {item}" for item in preview["risks"]] or ["未发现已知风险。"])
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本预览不创建/更新任何知识点、先修边或课标关联；`confirmed` 映射为 0。",
            "- 所有候选均为 `pending_review`；正式集成需要人工审核与批次回滚。",
            "- 先修自环类结果仅为候选映射冲突，不代表外部原始先修关系自环。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--validation", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    mapping_path = args.mapping or (args.out_dir / "mapping_result.json")
    validation_path = args.validation or (args.out_dir / "mapping_validation.json")
    try:
        mapping = read_json(mapping_path, label="mapping_result.json")
        if not isinstance(mapping, dict):
            raise PrototypeError("mapping_result.json must be an object")
        validation = _load_optional(validation_path)
        preview = build_preview(mapping, validation, args.source_dir)
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write_json(args.out_dir / "import_preview.json", preview)
    write_text(args.out_dir / "06_import_preview.md", _markdown(preview))
    print(
        "preview written (dry-run): "
        f"direct={preview['summary']['direct_suggestions']} "
        f"no_candidate={preview['summary']['no_candidate_nodes']} "
        f"high_risk={preview['summary']['high_risk_nodes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
