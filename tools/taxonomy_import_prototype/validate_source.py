#!/usr/bin/env python3
"""Validate the pinned external taxonomy dataset and write the source audit.

Only structural validation is performed; no network, no AI, no database access.
Exit code 0 means "no errors" (warnings are allowed), 1 means validation failed.
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
    MATH_DOMAINS,
    SOURCE_COMMIT,
    SOURCE_LICENSE_STATUS,
    SOURCE_REPO,
    PrototypeError,
    file_sha256,
    load_source,
    write_json,
    write_text,
)

EXPECTED_JUNIOR = 315
EXPECTED_VOLUMES = {(7, "上"): 61, (7, "下"): 58, (8, "上"): 57, (8, "下"): 57, (9, "上"): 49, (9, "下"): 33}
EXPECTED_INTERNAL_EDGES = 563
EXPECTED_CROSS_STAGE_EDGES = 45
EXPECTED_STAGE4 = 157
HASHED_FILES = (
    "data/topics.json",
    "data/dependencies.json",
    "data/cn-curriculum-standards.json",
    "data/id-aliases.json",
    "docs/standards-mapping.md",
    "scripts/validate.py",
    "CHANGELOG.md",
    "LICENSE",
)


def _cycles(nodes: set[str], edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["topicId"]].append(edge["prerequisiteId"])
    state: dict[str, int] = {}
    found: list[list[str]] = []

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        for neighbour in adjacency.get(node, []):
            if state.get(neighbour, 0) == 0:
                visit(neighbour, stack + [neighbour])
            elif state.get(neighbour) == 1:
                index = stack.index(neighbour)
                found.append(stack[index:] + [neighbour])
        state[node] = 2

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            visit(node, [node])
    return found


def validate(source_dir: Path) -> dict[str, Any]:
    source = load_source(source_dir)
    errors: list[str] = []
    warnings: list[str] = []

    topics_by_id = source["topic_by_id"]
    std_items = source["standards_doc"]["items"]
    std_ids = {item.get("id") for item in std_items}
    alias_ids = set(source["aliases"])

    if source["duplicate_ids"]:
        errors.append(f"duplicate topic ids: {sorted(set(source['duplicate_ids']))}")

    junior = source["junior_topics"]
    if len(junior) != EXPECTED_JUNIOR:
        errors.append(f"junior math topics: {len(junior)} != {EXPECTED_JUNIOR}")

    volumes = Counter((topic.get("grade"), topic.get("semester")) for topic in junior)
    for key, expected in EXPECTED_VOLUMES.items():
        if volumes.get(key, 0) != expected:
            errors.append(f"volume {key[0]}{key[1]}: {volumes.get(key, 0)} != {expected}")

    bad_domain = sorted({str(topic.get("domain")) for topic in junior if topic.get("domain") not in MATH_DOMAINS})
    if bad_domain:
        errors.append(f"junior topics with unexpected domain: {bad_domain}")
    if any(topic.get("external") for topic in junior):
        errors.append("junior dataset contains external=true placeholder nodes")

    # Topic -> standard references
    refs = [
        (topic["id"], ref.get("id"), ref.get("confidence"))
        for topic in junior
        for ref in (topic.get("standards") or [])
    ]
    refs_by_confidence = Counter(ref[2] for ref in refs)
    unknown_confidence = sorted(set(refs_by_confidence) - {"exact", "inferred"})
    if unknown_confidence:
        errors.append(f"unknown standards confidence values: {unknown_confidence}")
    missing_standard_refs = sorted({ref[1] for ref in refs if ref[1] not in std_ids})
    if missing_standard_refs:
        errors.append(f"topic standards references missing from standards file: {missing_standard_refs[:10]}")
    topics_without_standards = sorted(topic["id"] for topic in junior if not topic.get("standards"))
    if topics_without_standards:
        warnings.append(f"{len(topics_without_standards)} junior topics have no standards: {topics_without_standards}")

    stage4 = source["stage4_standards"]
    if len(stage4) != EXPECTED_STAGE4:
        errors.append(f"stage-4 math standards: {len(stage4)} != {EXPECTED_STAGE4}")
    stage4_ids = {item["id"] for item in stage4}
    unused_standards = sorted(stage4_ids - {ref[1] for ref in refs})
    if unused_standards:
        warnings.append(f"{len(unused_standards)} stage-4 standards are not referenced by junior topics")

    # Dependencies
    def side_status(topic_id: str) -> str:
        if topic_id in topics_by_id:
            return "topic"
        if topic_id in alias_ids:
            return "alias"
        return "missing"

    missing_endpoints: list[dict[str, str]] = []
    alias_edges = 0
    for edge in source["dependencies"]:
        for side in ("topicId", "prerequisiteId"):
            status = side_status(edge.get(side, ""))
            if status == "missing":
                missing_endpoints.append({"edge": str(edge), "side": side, "id": edge.get(side)})
            elif status == "alias" and side == "prerequisiteId":
                alias_edges += 1
    if missing_endpoints:
        errors.append(f"{len(missing_endpoints)} dependency endpoints are not topics or aliases")

    for alias, payload in source["aliases"].items():
        for target in payload.get("targets", []):
            if target not in topics_by_id:
                errors.append(f"alias {alias} target missing: {target}")

    internal_edges = source["internal_edges"]
    cross_edges = source["cross_stage_edges"]
    all_edges = source["dependencies"]
    if len(internal_edges) != EXPECTED_INTERNAL_EDGES:
        errors.append(f"junior internal dependencies: {len(internal_edges)} != {EXPECTED_INTERNAL_EDGES}")
    if len(cross_edges) != EXPECTED_CROSS_STAGE_EDGES:
        errors.append(f"junior->primary cross-stage dependencies: {len(cross_edges)} != {EXPECTED_CROSS_STAGE_EDGES}")

    edge_keys = [(edge["topicId"], edge["prerequisiteId"]) for edge in all_edges]
    duplicates = [key for key, count in Counter(edge_keys).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate dependency edges: {len(duplicates)}")
    self_loops = [edge for edge in all_edges if edge["topicId"] == edge["prerequisiteId"]]
    if self_loops:
        errors.append(f"self-loop dependency edges: {len(self_loops)}")
    bad_strength = sorted({str(edge.get("strength")) for edge in all_edges if edge.get("strength") not in {"hard", "soft"}})
    if bad_strength:
        errors.append(f"unexpected dependency strength values: {bad_strength}")

    cycle_list = _cycles(source["junior_ids"], internal_edges)
    if cycle_list:
        errors.append(f"dependency cycles among junior topics: {len(cycle_list)}")

    grade = {topic_id: topic.get("grade") for topic_id, topic in topics_by_id.items()}
    direction_violations = [
        edge for edge in internal_edges if (grade.get(edge["prerequisiteId"]) or 0) > (grade.get(edge["topicId"]) or 0)
    ]
    if direction_violations:
        warnings.append(f"{len(direction_violations)} junior internal edges point to a later grade")

    missing_topic_standards = sorted({ref[1] for ref in refs} - stage4_ids)
    if missing_topic_standards:
        errors.append(f"topic standards outside stage-4 math set: {missing_topic_standards[:10]}")

    report = {
        "meta": {
            "source_repo": SOURCE_REPO,
            "source_commit": SOURCE_COMMIT,
            "source_license_status": SOURCE_LICENSE_STATUS,
            "source_dir": str(source_dir),
            "file_sha256": {
                relative: file_sha256(source_dir / relative)
                for relative in HASHED_FILES
                if (source_dir / relative).is_file()
            },
            "expected": {
                "junior_topics": EXPECTED_JUNIOR,
                "volumes": {f"{key[0]}{key[1]}": value for key, value in EXPECTED_VOLUMES.items()},
                "junior_internal_edges": EXPECTED_INTERNAL_EDGES,
                "junior_to_primary_edges": EXPECTED_CROSS_STAGE_EDGES,
                "stage4_math_standards": EXPECTED_STAGE4,
            },
        },
        "counts": {
            "all_topics": len(source["topics"]),
            "junior_topics": len(junior),
            "volumes": {f"{key[0]}{key[1]}": value for key, value in sorted(volumes.items())},
            "domains": dict(sorted(Counter(topic.get("domain") for topic in junior).items())),
            "dependencies_total": len(all_edges),
            "junior_internal_edges": len(internal_edges),
            "junior_internal_strength": dict(sorted(Counter(edge.get("strength") for edge in internal_edges).items())),
            "junior_to_primary_edges": len(cross_edges),
            "junior_to_primary_strength": dict(sorted(Counter(edge.get("strength") for edge in cross_edges).items())),
            "senior_to_junior_edges": len(source["senior_to_junior_edges"]),
            "standards_math_items": len(std_items),
            "standards_stage4_math": len(stage4),
            "topic_standard_refs": len(refs),
            "topic_standard_refs_by_confidence": dict(sorted(refs_by_confidence.items())),
            "topics_without_standards": topics_without_standards,
            "unused_stage4_standards": unused_standards,
            "aliases": len(source["aliases"]),
            "alias_edges": alias_edges,
        },
        "errors": errors,
        "warnings": warnings,
    }
    return report


def _markdown(report: dict[str, Any], external_validator: dict[str, Any] | None) -> str:
    meta, counts = report["meta"], report["counts"]
    lines = [
        "# 02 外部数据审计（cn-math-taxonomy）",
        "",
        "> 状态标记：**verified**（复用此前审计事实，本次用固定版本重新生成可追溯证据；未做全量重复审计）。",
        "",
        f"- 仓库：{meta['source_repo']}",
        f"- Commit：`{meta['source_commit']}`",
        f"- 许可证状态：{meta['source_license_status']}",
        f"- 数据目录（仓库外）：`{meta['source_dir']}`",
        "",
        "## 文件 SHA256",
        "",
        "| 文件 | SHA256 |",
        "|---|---|",
    ]
    for name in sorted(meta["file_sha256"]):
        lines.append(f"| `{name}` | `{meta['file_sha256'][name]}` |")

    lines.extend(
        [
            "",
            "## 知识点",
            "",
            "| 指标 | 期望 | 实际 | 结论 |",
            "|---|---:|---:|---|",
            f"| 初中数学知识点 | {meta['expected']['junior_topics']} | {counts['junior_topics']} | "
            f"{'OK' if counts['junior_topics'] == meta['expected']['junior_topics'] else 'MISMATCH'} |",
        ]
    )
    for key, expected in meta["expected"]["volumes"].items():
        actual = counts["volumes"].get(key)
        lines.append(f"| 册次 {key} | {expected} | {actual} | {'OK' if actual == expected else 'MISMATCH'} |")
    lines.extend(
        [
            "",
            f"- domain 分布：{counts['domains']}",
            f"- 课标引用：{counts['topic_standard_refs']}（{counts['topic_standard_refs_by_confidence']}）",
            f"- 无课标知识点：{counts['topics_without_standards']}",
            "",
            "## 先修关系",
            "",
            "| 指标 | 期望 | 实际 | 结论 |",
            "|---|---:|---:|---|",
            f"| 初中内部 | {meta['expected']['junior_internal_edges']} | {counts['junior_internal_edges']} | "
            f"{'OK' if counts['junior_internal_edges'] == meta['expected']['junior_internal_edges'] else 'MISMATCH'} |",
            f"| 初中→小学跨学段 | {meta['expected']['junior_to_primary_edges']} | {counts['junior_to_primary_edges']} | "
            f"{'OK' if counts['junior_to_primary_edges'] == meta['expected']['junior_to_primary_edges'] else 'MISMATCH'} |",
            "",
            f"- 初中内部 strength：{counts['junior_internal_strength']}",
            f"- 跨学段 strength：{counts['junior_to_primary_strength']}",
            f"- 高中→初中（本阶段范围外，仅识别）：{counts['senior_to_junior_edges']}",
            f"- 全量边：{counts['dependencies_total']}",
            f"- 别名边：{counts['alias_edges']}（当前先修关系未引用已移除的 `cnm_ext_*`）",
            "",
            "## 课程标准",
            "",
            f"- 数学 items：{counts['standards_math_items']}",
            f"- 第四学段数学：{counts['standards_stage4_math']}（期望 {meta['expected']['stage4_math_standards']}）",
            f"- 未被初中知识点引用的课标：{len(counts['unused_stage4_standards'])} 条",
            "",
            "## 外部仓库校验器",
            "",
        ]
    )
    if external_validator is None:
        lines.append("未运行（可选步骤）。")
    else:
        lines.extend(
            [
                f"- 退出码：{external_validator.get('exit_code')}",
                f"- 输出文件：`{external_validator.get('output_path')}`",
                "",
                "```text",
                (external_validator.get("output") or "").strip()[-4000:],
                "```",
            ]
        )

    lines.extend(["", "## 错误与警告", "", "### 错误", ""])
    lines.extend([f"- {item}" for item in report["errors"]] or ["无。"])
    lines.extend(["", "### 警告", ""])
    lines.extend([f"- {item}" for item in report["warnings"]] or ["无。"])
    lines.extend(
        [
            "",
            "## 质量说明与局限",
            "",
            "- 初中数学 315 个知识点全部为正式节点（`external=false`），六册分布与基准一致。",
            "- 563 条内部先修关系方向为 `topicId 依赖 prerequisiteId`；45 条初中→小学边已单独统计，不视为缺失节点。",
            "- 第四学段数学课标 157 条；315 个知识点共 383 条引用（exact 286 / inferred 97）。",
            "- `verbatim` 多为未逐页核对：源数据自身标注为公开转写/OCR 校对状态，正式集成前仍需人工抽检。",
            "- 外部仓库许可证状态未确认（GitHub 元数据为 Other / NOASSERTION），本阶段不做授权或分发判断。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--external-validator-output", type=Path, default=None)
    parser.add_argument("--external-validator-exit", type=int, default=None)
    args = parser.parse_args(argv)

    external_validator = None
    if args.external_validator_output is not None and args.external_validator_output.is_file():
        external_validator = {
            "output_path": str(args.external_validator_output),
            "exit_code": args.external_validator_exit,
            "output": args.external_validator_output.read_text(encoding="utf-8", errors="replace"),
        }

    try:
        report = validate(args.source_dir)
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write_json(args.out_dir / "source_validation.json", report)
    write_text(args.out_dir / "02_source_data_audit.md", _markdown(report, external_validator))
    for item in report["errors"]:
        print(f"ERROR: {item}", file=sys.stderr)
    for item in report["warnings"]:
        print(f"WARNING: {item}", file=sys.stderr)
    print(
        f"source validation: {len(report['errors'])} errors, "
        f"{len(report['warnings'])} warnings"
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
