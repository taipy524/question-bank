"""Shared helpers for the taxonomy import prototype.

The prototype is deliberately standalone: standard library only, no imports from
the FastAPI application, no ChromaDB, no AI provider calls and no database writes.
All outputs are written under an explicit ``--out-dir``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

SOURCE_REPO = "https://github.com/xiaoyang111222/cn-math-taxonomy"
SOURCE_COMMIT = "cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab"
SOURCE_LICENSE_STATUS = "unconfirmed (GitHub license metadata: Other / NOASSERTION)"

PROTOTYPE_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = Path(
    os.environ.get("CNM_SOURCE_DIR", "/workspace/.opencode/tmp/cn-math-taxonomy-cf73951")
)
DEFAULT_INTERNAL_DUMP = Path(
    os.environ.get(
        "QB_INTERNAL_DUMP",
        "/workspace/.opencode/tmp/finalize-20261025_235534/mysql.sql",
    )
)
DEFAULT_OUT_DIR = PROTOTYPE_ROOT / "reports"

JUNIOR_GRADES = (7, 8, 9)
MATH_DOMAINS = ("数与代数", "图形与几何", "统计与概率", "综合与实践")

# Internal top-level category -> external curriculum domain family.
CATEGORY_DOMAIN_FAMILY = {
    "数与式": "数与代数",
    "方程与不等式": "数与代数",
    "函数": "数与代数",
    "图形与几何": "图形与几何",
    "图形变换": "图形与几何",
    "统计与概率": "统计与概率",
    "综合与应用": "综合与实践",
}

SEMANTIC_JACCARD_THRESHOLD = 0.6
INTERNAL_DUPLICATE_THRESHOLD = 0.8
EXACT_CONFIDENCE = 0.9
EXACT_CONFLICT_CONFIDENCE = 0.5
SPLIT_MIN_EXTERNALS = 3


class PrototypeError(RuntimeError):
    """Raised when an input file is missing, malformed or unsafe to consume."""


# ---------------------------------------------------------------------------
# Name normalisation and similarity
# ---------------------------------------------------------------------------

_PUNCTUATION_RE = re.compile(
    r"[\s\u3000.,，。、;；:：!！?？'\"“”‘’()（）\[\]【】{}<>《》/\\|·—–\-_+*]+"
)


def normalize_name(value: str) -> str:
    """Conservative normalisation used for exact matching and bigrams."""
    text = unicodedata.normalize("NFKC", value or "").lower()
    return _PUNCTUATION_RE.sub("", text)


def char_bigrams(value: str) -> set[str]:
    text = normalize_name(value)
    if len(text) < 2:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


def bigram_jaccard(left: str, right: str) -> float:
    a, b = char_bigrams(left), char_bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# JSON / CSV / hashing helpers (deterministic output)
# ---------------------------------------------------------------------------


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, *, label: str) -> Any:
    if not path.is_file():
        raise PrototypeError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PrototypeError(f"{label} is not valid JSON: {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return value


# ---------------------------------------------------------------------------
# Source data
# ---------------------------------------------------------------------------


def load_source(source_dir: Path) -> dict[str, Any]:
    """Load the pinned external dataset and derive the 315/563/157 working sets."""
    source_dir = Path(source_dir)
    topics = read_json(source_dir / "data" / "topics.json", label="topics.json")
    if not isinstance(topics, list):
        raise PrototypeError("topics.json must be a JSON array")
    dependencies = read_json(source_dir / "data" / "dependencies.json", label="dependencies.json")
    if not isinstance(dependencies, list):
        raise PrototypeError("dependencies.json must be a JSON array")
    standards = read_json(
        source_dir / "data" / "cn-curriculum-standards.json",
        label="cn-curriculum-standards.json",
    )
    if not isinstance(standards, dict) or not isinstance(standards.get("items"), list):
        raise PrototypeError("cn-curriculum-standards.json must contain an 'items' array")
    aliases_doc = read_json(source_dir / "data" / "id-aliases.json", label="id-aliases.json")
    aliases = aliases_doc.get("aliases") if isinstance(aliases_doc, dict) else None
    if not isinstance(aliases, dict):
        raise PrototypeError("id-aliases.json must contain an 'aliases' object")

    topic_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for topic in topics:
        topic_id = topic.get("id")
        if not isinstance(topic_id, str):
            raise PrototypeError(f"topic without a string id: {topic!r}")
        if topic_id in topic_by_id:
            duplicate_ids.append(topic_id)
        topic_by_id[topic_id] = topic

    junior = [
        topic
        for topic in topics
        if str(topic.get("id", "")).startswith("cnm_") and topic.get("grade") in JUNIOR_GRADES
    ]
    primary = [
        topic
        for topic in topics
        if str(topic.get("id", "")).startswith("cnm_") and 1 <= int(topic.get("grade") or 0) <= 6
    ]
    junior_ids = {topic["id"] for topic in junior}
    primary_ids = {topic["id"] for topic in primary}

    stage4_standards = [
        item
        for item in standards["items"]
        if str(item.get("id", "")).split(":")[-1].startswith("4.")
        and item.get("domain") in MATH_DOMAINS
    ]

    internal_edges = [
        edge
        for edge in dependencies
        if edge.get("topicId") in junior_ids and edge.get("prerequisiteId") in junior_ids
    ]
    cross_stage_edges = [
        edge
        for edge in dependencies
        if edge.get("topicId") in junior_ids and edge.get("prerequisiteId") in primary_ids
    ]
    senior_to_junior_edges = [
        edge
        for edge in dependencies
        if edge.get("topicId") not in junior_ids
        and edge.get("topicId") not in primary_ids
        and edge.get("prerequisiteId") in junior_ids
    ]

    return {
        "source_dir": source_dir,
        "topics": topics,
        "topic_by_id": topic_by_id,
        "duplicate_ids": duplicate_ids,
        "junior_topics": sorted(junior, key=lambda item: item["id"]),
        "primary_topics": sorted(primary, key=lambda item: item["id"]),
        "junior_ids": junior_ids,
        "primary_ids": primary_ids,
        "dependencies": dependencies,
        "internal_edges": internal_edges,
        "cross_stage_edges": cross_stage_edges,
        "senior_to_junior_edges": senior_to_junior_edges,
        "standards_doc": standards,
        "stage4_standards": sorted(stage4_standards, key=lambda item: item["id"]),
        "aliases_doc": aliases_doc,
        "aliases": aliases,
    }


# ---------------------------------------------------------------------------
# Internal snapshot helpers
# ---------------------------------------------------------------------------


REQUIRED_SNAPSHOT_FIELDS = (
    "internal_id",
    "name",
    "slug",
    "subject_id",
    "subject_name",
    "parent_id",
    "parent_path",
)


def load_internal_snapshot(path: Path) -> dict[str, Any]:
    payload = read_json(path, label="internal snapshot")
    if not isinstance(payload, dict) or not isinstance(payload.get("knowledge_points"), list):
        raise PrototypeError("internal snapshot must contain a 'knowledge_points' array")
    rows = payload["knowledge_points"]
    ids = set()
    for row in rows:
        missing = [field for field in REQUIRED_SNAPSHOT_FIELDS if field not in row]
        if missing:
            raise PrototypeError(f"snapshot row missing fields {missing}: {row!r}")
        if row["internal_id"] in ids:
            raise PrototypeError(f"duplicate internal_id in snapshot: {row['internal_id']}")
        ids.add(row["internal_id"])
    return payload


def internal_levels(snapshot: dict[str, Any]) -> dict[int, str]:
    """Return internal_id -> structural|category|leaf."""
    rows = snapshot["knowledge_points"]
    by_id = {row["internal_id"]: row for row in rows}
    levels: dict[int, str] = {}
    for row in rows:
        if row.get("parent_id") is None:
            levels[row["internal_id"]] = "structural"
            continue
        parent = by_id.get(row["parent_id"])
        if parent is not None and parent.get("parent_id") is None:
            levels[row["internal_id"]] = "category"
        else:
            levels[row["internal_id"]] = "leaf"
    return levels


def internal_category_name(row: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> str | None:
    """Top-level category name for a category/leaf node.

    The internal tree is ``root -> category -> leaf`` (three levels today).  A
    category node returns its own name; a leaf returns the name of the node whose
    parent is the structural root.  The structural root returns ``None``.
    """
    current = row
    seen: set[int] = set()
    while True:
        parent_id = current.get("parent_id")
        if parent_id is None:
            return None
        if current["internal_id"] in seen:
            return None
        seen.add(current["internal_id"])
        parent = by_id.get(parent_id)
        if parent is None:
            return None
        if parent.get("parent_id") is None:
            return current["name"]
        current = parent
