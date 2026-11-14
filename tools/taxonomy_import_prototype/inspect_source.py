#!/usr/bin/env python3
"""Inspect the pinned external taxonomy dataset and print/write statistics.

Read-only: only writes ``source_inspection.json`` / ``source_inspection.md`` under
``--out-dir``.
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
    SOURCE_COMMIT,
    SOURCE_LICENSE_STATUS,
    SOURCE_REPO,
    PrototypeError,
    file_sha256,
    load_source,
    write_json,
    write_text,
)

SOURCE_FILES = (
    "data/topics.json",
    "data/dependencies.json",
    "data/cn-curriculum-standards.json",
    "data/id-aliases.json",
    "docs/standards-mapping.md",
    "scripts/validate.py",
    "CHANGELOG.md",
    "LICENSE",
)


def _counter_rows(counter: Counter[Any], label: str) -> list[str]:
    lines = [f"| {label} | 数量 |", "|---|---:|"]
    for key in sorted(counter, key=lambda item: str(item)):
        lines.append(f"| {key} | {counter[key]} |")
    return lines


def inspect(source_dir: Path) -> dict[str, Any]:
    source = load_source(source_dir)
    junior = source["junior_topics"]
    standards = source["stage4_standards"]
    aliases = source["aliases"]
    topics = source["topics"]

    volumes = Counter((topic.get("grade"), topic.get("semester")) for topic in junior)
    domains = Counter(topic.get("domain") for topic in junior)
    types = Counter(topic.get("type") for topic in junior)
    chapters = {topic.get("chapter") for topic in junior}
    topic_standards = [
        (topic["id"], ref.get("id"), ref.get("confidence"))
        for topic in junior
        for ref in (topic.get("standards") or [])
    ]
    confidence = Counter(ref[2] for ref in topic_standards)
    standard_ids = {item["id"] for item in standards}

    hashes = {
        relative: file_sha256(source_dir / relative)
        for relative in SOURCE_FILES
        if (source_dir / relative).is_file()
    }

    return {
        "meta": {
            "source_repo": SOURCE_REPO,
            "source_commit": SOURCE_COMMIT,
            "source_license_status": SOURCE_LICENSE_STATUS,
            "source_dir": str(source_dir),
            "file_sha256": hashes,
        },
        "all_subjects": {
            "topics_total": len(topics),
            "topics_by_id_prefix": dict(
                Counter(topic["id"].split("_")[0] for topic in topics)
            ),
        },
        "junior_math": {
            "topic_total": len(junior),
            "by_volume": {f"{grade}{semester}": volumes[(grade, semester)] for grade, semester in sorted(volumes)},
            "by_domain": dict(sorted(domains.items())),
            "by_type": dict(sorted(types.items())),
            "distinct_chapters": len(chapters),
            "external_flag_true": sum(1 for topic in junior if topic.get("external")),
            "standards_refs": len(topic_standards),
            "standards_refs_by_confidence": dict(sorted(confidence.items())),
            "topics_without_standards": sorted(
                topic["id"] for topic in junior if not topic.get("standards")
            ),
            "standard_refs_missing_from_file": sorted(
                {ref[1] for ref in topic_standards if ref[1] not in standard_ids}
            ),
        },
        "dependencies": {
            "edges_total": len(source["dependencies"]),
            "junior_internal_edges": len(source["internal_edges"]),
            "junior_internal_by_strength": dict(
                sorted(Counter(edge.get("strength") for edge in source["internal_edges"]).items())
            ),
            "junior_to_primary_edges": len(source["cross_stage_edges"]),
            "senior_to_junior_edges": len(source["senior_to_junior_edges"]),
            "by_strength": dict(
                sorted(Counter(edge.get("strength") for edge in source["dependencies"]).items())
            ),
        },
        "standards": {
            "math_items_total": len(source["standards_doc"]["items"]),
            "stage4_math_total": len(standards),
            "stage4_by_domain": dict(sorted(Counter(item.get("domain") for item in standards).items())),
            "stage4_verbatim": dict(sorted(Counter(str(item.get("verbatim")) for item in standards).items())),
        },
        "aliases": {
            "alias_total": len(aliases),
            "alias_ids": sorted(aliases),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    junior = report["junior_math"]
    deps = report["dependencies"]
    standards = report["standards"]
    lines = [
        "# 外部数据检视（cn-math-taxonomy）",
        "",
        f"- 仓库：{meta['source_repo']}",
        f"- Commit：`{meta['source_commit']}`",
        f"- 许可证状态：{meta['source_license_status']}",
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
            "## 初中数学知识点",
            "",
            f"- 总数：**{junior['topic_total']}**",
            f"- 六册分布：{junior['by_volume']}",
            f"- domain 分布：{junior['by_domain']}",
            f"- 类型分布：{junior['by_type']}",
            f"- 章节数：{junior['distinct_chapters']}",
            f"- `external=true` 数量：{junior['external_flag_true']}",
            f"- 课标引用：{junior['standards_refs']}（{junior['standards_refs_by_confidence']}）",
            f"- 无课标知识点：{junior['topics_without_standards']}",
            f"- 引用但文件中不存在的课标：{junior['standard_refs_missing_from_file']}",
            "",
            "## 先修关系",
            "",
            f"- 全量边：{deps['edges_total']}",
            f"- 初中内部：**{deps['junior_internal_edges']}**（{deps['junior_internal_by_strength']}）",
            f"- 初中→小学跨学段：**{deps['junior_to_primary_edges']}**",
            f"- 高中→初中（超出本阶段）：{deps['senior_to_junior_edges']}",
            f"- 全量 strength：{deps['by_strength']}",
            "",
            "## 课程标准",
            "",
            f"- 数学 items 总数：{standards['math_items_total']}",
            f"- 第四学段数学：**{standards['stage4_math_total']}**（{standards['stage4_by_domain']}）",
            f"- verbatim 分布：{standards['stage4_verbatim']}",
            "",
            "## ID 别名",
            "",
            f"- 别名总数：{report['aliases']['alias_total']}（均为已移除的 `cnm_ext_*` 外部节点）",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    try:
        report = inspect(args.source_dir)
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    write_json(args.out_dir / "source_inspection.json", report)
    write_text(args.out_dir / "source_inspection.md", _markdown(report))
    print(f"source inspection written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
