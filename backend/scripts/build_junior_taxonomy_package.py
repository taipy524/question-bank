#!/usr/bin/env python3
"""Build the reproducible junior-high math taxonomy data package.

Reads the reviewed external snapshot (cf73951), keeps only the junior-high
math slice, validates it, and writes a self-contained package with provenance.

Usage:
    python scripts/build_junior_taxonomy_package.py \
        --source-dir /home/yuwan/taxonomy-external \
        --out ../data/cn-math-taxonomy/cf73951 \
        --commit cf73951

The output layout matches ``app.services.taxonomy_source_import.load_dataset``::

    <out>/data/topics.json
    <out>/data/dependencies.json
    <out>/data/cn-curriculum-standards.json
    <out>/data/id-aliases.json
    <out>/manifest.json
    <out>/LICENSE
    <out>/README.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

JUNIOR_GRADES = (7, 8, 9)
MATH_DOMAINS = ("数与代数", "图形与几何", "统计与概率", "综合与实践")
EXPECTED = {
    "topics": 315,
    "internal_edges": 563,
    "standards": 157,
    "topic_standards": 383,
}
CROSS_STAGE_EXPECTED = 45


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--commit", default="cf73951")
    parser.add_argument(
        "--repo-url",
        default="https://github.com/xiaoyang111222/cn-math-taxonomy",
    )
    args = parser.parse_args()

    src = args.source_dir / "data"
    topics = load_json(src / "topics.json")
    dependencies = load_json(src / "dependencies.json")
    standards_doc = load_json(src / "cn-curriculum-standards.json")
    aliases_doc = load_json(src / "id-aliases.json")

    junior = sorted(
        [
            t
            for t in topics
            if str(t.get("id", "")).startswith("cnm_")
            and t.get("grade") in JUNIOR_GRADES
        ],
        key=lambda t: t["id"],
    )
    junior_ids = {t["id"] for t in junior}
    internal_edges = [
        e
        for e in dependencies
        if e.get("topicId") in junior_ids and e.get("prerequisiteId") in junior_ids
    ]
    cross_edges = [
        e
        for e in dependencies
        if e.get("topicId") in junior_ids and e.get("prerequisiteId") not in junior_ids
    ]
    standards = [
        s
        for s in standards_doc["items"]
        if str(s.get("id", "")).split(":")[-1].startswith("4.")
        and s.get("domain") in MATH_DOMAINS
    ]
    standards.sort(key=lambda s: s["id"])
    topic_standards = [
        {
            "topic_id": t["id"],
            "standard_id": ref["id"],
            "confidence": ref.get("confidence"),
            "note": ref.get("note"),
        }
        for t in junior
        for ref in (t.get("standards") or [])
    ]

    errors: list[str] = []
    if len(junior) != EXPECTED["topics"]:
        errors.append(f"topics {len(junior)} != {EXPECTED['topics']}")
    if len(internal_edges) != EXPECTED["internal_edges"]:
        errors.append(f"internal_edges {len(internal_edges)} != {EXPECTED['internal_edges']}")
    if len(standards) != EXPECTED["standards"]:
        errors.append(f"standards {len(standards)} != {EXPECTED['standards']}")
    if len(topic_standards) != EXPECTED["topic_standards"]:
        errors.append(f"topic_standards {len(topic_standards)} != {EXPECTED['topic_standards']}")
    if len(cross_edges) != CROSS_STAGE_EXPECTED:
        errors.append(f"cross_stage {len(cross_edges)} != {CROSS_STAGE_EXPECTED}")

    topic_ids = [t["id"] for t in junior]
    if len(set(topic_ids)) != len(topic_ids):
        errors.append("duplicate topic ids")
    standard_ids = [s["id"] for s in standards]
    if len(set(standard_ids)) != len(standard_ids):
        errors.append("duplicate standard ids")
    for edge in internal_edges:
        if edge["topicId"] == edge["prerequisiteId"]:
            errors.append(f"self loop: {edge}")
        if edge.get("strength") not in {"hard", "soft"}:
            errors.append(f"bad strength: {edge}")
    if len({(e["topicId"], e["prerequisiteId"]) for e in internal_edges}) != len(internal_edges):
        errors.append("duplicate internal edges")
    for ref in topic_standards:
        if ref["standard_id"] not in set(standard_ids):
            errors.append(f"missing standard: {ref}")
        if ref["confidence"] not in {"exact", "inferred"}:
            errors.append(f"bad confidence: {ref}")

    def has_cycle() -> bool:
        adj: dict[str, list[str]] = {}
        for e in internal_edges:
            adj.setdefault(e["topicId"], []).append(e["prerequisiteId"])
        state: dict[str, int] = {}

        def visit(node: str) -> bool:
            state[node] = 1
            for nxt in adj.get(node, ()):
                if state.get(nxt, 0) == 0:
                    if visit(nxt):
                        return True
                elif state.get(nxt) == 1:
                    return True
            state[node] = 2
            return False

        return any(state.get(n, 0) == 0 and visit(n) for n in adj)

    if has_cycle():
        errors.append("dependency cycle detected")

    if errors:
        print("VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(" -", error, file=sys.stderr)
        return 1

    out = args.out
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "topics.json").write_text(
        json.dumps(junior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "data" / "dependencies.json").write_text(
        json.dumps(internal_edges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "data" / "cn-curriculum-standards.json").write_text(
        json.dumps(
            {**{k: v for k, v in standards_doc.items() if k != "items"}, "items": standards},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "data" / "id-aliases.json").write_text(
        json.dumps(aliases_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "data" / "topic-standards.json").write_text(
        json.dumps(topic_standards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    license_src = args.source_dir / "LICENSE"
    if license_src.is_file():
        shutil.copyfile(license_src, out / "LICENSE")

    manifest = {
        "name": "cn-math-taxonomy junior-high math package",
        "source": {
            "repo_url": args.repo_url,
            "commit": args.commit,
            "commit_note": "short SHA as published by the source repository",
            "retrieved_from": str(args.source_dir),
        },
        "license": {
            "id": "CC BY-NC 4.0",
            "url": "https://creativecommons.org/licenses/by-nc/4.0/",
            "note": "Non-commercial use only. Commercial use requires separate permission from the source author.",
            "file_sha256": sha256(out / "LICENSE") if (out / "LICENSE").is_file() else None,
        },
        "scope": {
            "included": [
                f"{EXPECTED['topics']} junior-high math knowledge points",
                f"{EXPECTED['internal_edges']} internal prerequisite edges",
                f"{EXPECTED['standards']} curriculum standards",
                f"{EXPECTED['topic_standards']} topic-standard mappings",
            ],
            "excluded": [
                f"{len(cross_edges)} primary-to-junior prerequisite edges (not imported in this phase)",
                "external practice questions",
                "primary school, high school and other subjects",
            ],
        },
        "counts": {
            "topics": len(junior),
            "internal_edges": len(internal_edges),
            "cross_stage_edges_excluded": len(cross_edges),
            "standards": len(standards),
            "topic_standards": len(topic_standards),
            "grades": dict(sorted(Counter(t.get("grade") for t in junior).items())),
            "strengths": dict(sorted(Counter(e.get("strength") for e in internal_edges).items())),
            "confidence": dict(sorted(Counter(r["confidence"] for r in topic_standards).items())),
        },
        "source_files_sha256": {
            name: sha256(src / name)
            for name in (
                "topics.json",
                "dependencies.json",
                "cn-curriculum-standards.json",
                "id-aliases.json",
            )
        },
        "package_files_sha256": {
            str(p.relative_to(out)).replace("\\", "/"): sha256(p)
            for p in sorted((out / "data").glob("*.json"))
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "backend/scripts/build_junior_taxonomy_package.py",
        "modifications": [
            "Filtered topics to cnm_* with grade 7-9",
            "Filtered dependencies to both endpoints in the junior set",
            "Filtered standards to CMS 2022 4.x math domains",
            "Flattened topic standards into data/topic-standards.json (also kept on each topic)",
            "Excluded 45 primary-to-junior edges",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    readme = f"""# 初中数学知识体系数据包（cf73951）

来源：[{args.repo_url}]({args.repo_url})，固定提交 `{args.commit}`。

许可证：**CC BY-NC 4.0**（署名—非商业性使用 4.0 国际）。
商业用途需另行获得原作者授权。许可证全文见同目录 `LICENSE`。

## 内容

| 文件 | 说明 |
|---|---|
| `data/topics.json` | {len(junior)} 个初中数学知识点 |
| `data/dependencies.json` | {len(internal_edges)} 条初中内部先修关系 |
| `data/cn-curriculum-standards.json` | {len(standards)} 条课程标准 |
| `data/topic-standards.json` | {len(topic_standards)} 条知识点—课程标准映射 |
| `data/id-aliases.json` | 外部 ID 别名 |
| `manifest.json` | 来源、计数、校验值与修改说明 |

## 未包含

- {len(cross_edges)} 条小学→初中先修关系（本阶段不导入）
- 外部配套题目
- 小学、高中及其他学科数据

## 修改说明

本数据包由 `backend/scripts/build_junior_taxonomy_package.py` 从上游数据过滤生成，
仅保留初中数学范围；未修改任何知识点、关系或课标的内容与含义。

## 重新生成

```bash
cd backend
python scripts/build_junior_taxonomy_package.py \\
  --source-dir /path/to/cn-math-taxonomy \\
  --out ../data/cn-math-taxonomy/cf73951 \\
  --commit cf73951
```
"""
    (out / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))
    print(f"package written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
