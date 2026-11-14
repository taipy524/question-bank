"""Synthetic fixtures for the prototype tests (no database, no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import stable_hash  # noqa: E402


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_source(tmp_path: Path, *, topics, dependencies, standards_items=None, aliases=None) -> Path:
    source = tmp_path / "source"
    write_json(source / "data" / "topics.json", topics)
    write_json(source / "data" / "dependencies.json", dependencies)
    write_json(
        source / "data" / "cn-curriculum-standards.json",
        {"source": {"title": "synthetic"}, "items": standards_items or []},
    )
    write_json(source / "data" / "id-aliases.json", {"description": "synthetic", "aliases": aliases or {}})
    return source


def make_snapshot(tmp_path: Path, *, subject_name: str, rows) -> Path:
    knowledge_points = []
    for row in rows:
        knowledge_points.append(
            {
                "internal_id": row["internal_id"],
                "name": row["name"],
                "slug": row.get("slug", f"kp-{row['internal_id']}"),
                "subject_id": row.get("subject_id", 1),
                "subject_name": subject_name,
                "parent_id": row.get("parent_id"),
                "parent_path": row.get("parent_path", subject_name),
            }
        )
    payload = {
        "meta": {
            "source": "synthetic",
            "exported_at": "2026-01-01 00:00:00",
            "row_count": len(knowledge_points),
            "snapshot_sha256": stable_hash(knowledge_points),
        },
        "knowledge_points": knowledge_points,
    }
    path = tmp_path / "internal_snapshot.json"
    write_json(path, payload)
    return path


def standard_item(standard_id: str, *, domain: str = "数与代数") -> dict:
    return {
        "id": standard_id,
        "domain": domain,
        "section": "synthetic",
        "clause": "(1)",
        "text": "synthetic standard",
        "page_or_ref": "n/a",
        "verbatim": None,
        "text_status": "synthetic",
    }


def topic(
    topic_id: str,
    name: str,
    *,
    domain: str = "数与代数",
    grade: int = 9,
    semester: str = "上",
    chapter: str = "synthetic",
    standards=None,
    external: bool = False,
) -> dict:
    return {
        "id": topic_id,
        "name": name,
        "domain": domain,
        "grade": grade,
        "semester": semester,
        "chapter": chapter,
        "type": "conceptual",
        "description": "",
        "mastery_criteria": [],
        "diagnostic_question": {"question": "", "answer": ""},
        "external": external,
        "standards": standards or [],
    }


def mapping_snapshot_rows() -> list[dict]:
    """Internal tree used by the synthetic mapping tests.

    root -> category -> leaf (plus a duplicate leaf name for the N-1 case).
    """
    return [
        {"internal_id": 1, "name": "数学", "parent_id": None, "parent_path": "数学"},
        {"internal_id": 2, "name": "方程与不等式", "parent_id": 1, "parent_path": "数学"},
        {"internal_id": 3, "name": "一元二次方程", "parent_id": 2, "parent_path": "数学 > 方程与不等式"},
        {"internal_id": 4, "name": "一元二次方程解法", "parent_id": 2, "parent_path": "数学 > 方程与不等式"},
        {"internal_id": 5, "name": "函数", "parent_id": 1, "parent_path": "数学"},
        {"internal_id": 6, "name": "正比例函数", "parent_id": 5, "parent_path": "数学 > 函数"},
        {"internal_id": 7, "name": "反比例函数", "parent_id": 5, "parent_path": "数学 > 函数"},
        {"internal_id": 8, "name": "统计与概率", "parent_id": 1, "parent_path": "数学"},
        {"internal_id": 9, "name": "统计图表", "parent_id": 8, "parent_path": "数学 > 统计与概率"},
        {"internal_id": 10, "name": "众数", "parent_id": 8, "parent_path": "数学 > 统计与概率"},
        {"internal_id": 11, "name": "众数", "parent_id": 8, "parent_path": "数学 > 统计与概率"},
        {"internal_id": 13, "name": "数与式", "parent_id": 1, "parent_path": "数学"},
        {"internal_id": 14, "name": "数轴", "parent_id": 13, "parent_path": "数学 > 数与式"},
    ]


def mapping_topics() -> list[dict]:
    return [
        topic("cnm_001", "一元二次方程", standards=[{"id": "cms-2022:4.NA.01", "confidence": "exact"}]),
        topic("cnm_002", "一元二次方程的解法", standards=[{"id": "cms-2022:4.NA.02", "confidence": "inferred"}]),
        topic("cnm_003", "正比例函数"),
        topic("cnm_004", "正比例函"),
        topic("cnm_005", "统计图表", domain="统计与概率"),
        topic("cnm_006", "数轴", domain="图形与几何"),
        topic("cnm_007", "众数", domain="统计与概率"),
        topic("cnm_008", "完全无关主题"),
        topic("cnm_009", "反比例函数"),
        topic("cnm_p001", "整数四则运算", grade=4),
        topic("cnm_s001", "集合", grade=10),
    ]


def mapping_standards() -> list[dict]:
    return [
        standard_item("cms-2022:4.NA.01", domain="数与代数"),
        standard_item("cms-2022:4.NA.02", domain="数与代数"),
        standard_item("cms-2022:4.GA.01", domain="图形与几何"),
    ]


def mapping_dependencies() -> list[dict]:
    return [
        {"topicId": "cnm_003", "prerequisiteId": "cnm_004", "strength": "hard", "reason": "synthetic self-loop after mapping"},
        {"topicId": "cnm_001", "prerequisiteId": "cnm_p001", "strength": "soft", "reason": "cross-stage"},
        {"topicId": "cnm_001", "prerequisiteId": "cnm_002", "strength": "hard", "reason": "internal"},
        {"topicId": "cnm_s001", "prerequisiteId": "cnm_001", "strength": "soft", "reason": "senior"},
    ]
