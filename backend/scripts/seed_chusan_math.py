"""Idempotent initialization of 初三数学 base data.

Creates/reuses:
  - Subject: 初三数学 (renames the legacy 初中数学 subject in place so existing
    question/tag/knowledge-point associations are preserved)
  - Tag category 用途 + tags (题型/难度/来源 already have dedicated fields:
    Question.q_type / Question.difficulty / Question.source, so no tags for them)
  - Knowledge point tree: 初三数学 > 7 categories > concrete knowledge points

Uses the project's existing xlsx import services, so re-running is safe:
existing nodes/duplicate tag names are skipped instead of duplicated.

Usage (inside the backend container, from /app):
    python scripts/seed_chusan_math.py
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook
from sqlalchemy import func, select

from app.db.session import SessionLocal, engine
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.tag import Tag
from app.services import kp_import_service, tag_import_service

SUBJECT_NAME = "初三数学"
SUBJECT_SLUG = "gmath"
SUBJECT_DESCRIPTION = "初三（九年级）数学"
LEGACY_SUBJECT_NAMES = ("初中数学", "初级数学")

TAG_ROWS = [
    ("基础巩固", "用途", "#4F81BD"),
    ("专题训练", "用途", "#5B9BD5"),
    ("综合应用", "用途", "#70AD47"),
    ("中考复习", "用途", "#ED7D31"),
]

KP_TREE: dict[str, list[str]] = {
    "数与式": [
        "实数与数的运算",
        "整式运算",
        "因式分解",
        "分式及其运算",
        "二次根式及其运算",
    ],
    "方程与不等式": [
        "一元一次方程",
        "二元一次方程组",
        "一元一次不等式与不等式组",
        "分式方程",
        "一元二次方程",
        "方程的实际应用",
    ],
    "函数": [
        "平面直角坐标系",
        "函数的概念与表示",
        "一次函数",
        "反比例函数",
        "二次函数",
        "函数图像与性质",
        "函数与方程",
        "函数实际应用",
    ],
    "图形与几何": [
        "直线、射线与线段",
        "角与平行线",
        "三角形及其性质",
        "全等三角形",
        "等腰三角形",
        "勾股定理",
        "相似三角形",
        "四边形",
        "平行四边形",
        "矩形、菱形与正方形",
        "圆的基本性质",
        "圆周角与圆心角",
        "切线及其性质",
        "圆与三角形综合",
        "锐角三角函数",
        "解直角三角形",
        "图形面积与长度计算",
    ],
    "图形变换": [
        "轴对称",
        "平移",
        "旋转",
        "中心对称",
        "图形变换与坐标",
    ],
    "统计与概率": [
        "数据收集与整理",
        "统计图表",
        "平均数、中位数与众数",
        "方差",
        "简单随机事件",
        "概率计算",
    ],
    "综合与应用": [
        "代数综合",
        "函数综合",
        "几何证明",
        "几何计算",
        "动态几何问题",
        "最值问题",
        "实际应用建模",
    ],
}

KP_COLS = [
    "学科名称",
    "一级目录",
    "二级目录",
    "三级目录",
    "四级目录",
    "五级目录",
    "六级目录",
    "七级目录",
    "八级目录",
]


def _build_tag_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "标签导入"
    ws.append(["名称", "分类", "颜色"])
    for row in TAG_ROWS:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_kp_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "知识点导入"
    ws.append(KP_COLS)
    for category, points in KP_TREE.items():
        for point in points:
            # root(初三数学) > category > concrete point
            ws.append([SUBJECT_NAME, SUBJECT_NAME, category, point] + [""] * 5)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _ensure_subject(db) -> tuple[Subject, str]:
    subject = await db.scalar(select(Subject).where(Subject.name == SUBJECT_NAME))
    if subject:
        return subject, "reused"

    legacy = await db.scalar(
        select(Subject).where(Subject.name.in_(LEGACY_SUBJECT_NAMES))
    )
    if legacy:
        legacy.name = SUBJECT_NAME
        if not legacy.description:
            legacy.description = SUBJECT_DESCRIPTION
        await db.commit()
        await db.refresh(legacy)
        return legacy, "renamed"

    slug = SUBJECT_SLUG
    if await db.scalar(select(Subject).where(Subject.slug == slug)):
        slug = f"{SUBJECT_SLUG}-9"
    subject = Subject(
        name=SUBJECT_NAME,
        slug=slug,
        description=SUBJECT_DESCRIPTION,
        required_review_count=1,
        created_by=1,
        updated_by=1,
    )
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject, "created"


async def _ensure_root(db, subject: Subject) -> None:
    """Rename the legacy root knowledge point in place (keeps id + associations)."""
    root = await db.scalar(
        select(KnowledgePoint).where(
            KnowledgePoint.subject_id == subject.id,
            KnowledgePoint.parent_id.is_(None),
            KnowledgePoint.name == SUBJECT_NAME,
        )
    )
    if root:
        return
    legacy_root = await db.scalar(
        select(KnowledgePoint).where(
            KnowledgePoint.subject_id == subject.id,
            KnowledgePoint.parent_id.is_(None),
            KnowledgePoint.name.in_(LEGACY_SUBJECT_NAMES),
        )
    )
    if legacy_root:
        legacy_root.name = SUBJECT_NAME
        await db.commit()


async def main() -> None:
    async with SessionLocal() as db:
        subject, subject_action = await _ensure_subject(db)
        await _ensure_root(db, subject)
        print(f"[subject] {subject.name} (id={subject.id}, {subject_action})")

        before_tags = await db.scalar(
            select(func.count(Tag.id)).where(Tag.subject_id == subject.id)
        )
        tag_result = await tag_import_service.import_excel(
            db,
            subject_id=subject.id,
            file_bytes=_build_tag_xlsx(),
            user_id=1,
        )
        after_tags = await db.scalar(
            select(func.count(Tag.id)).where(Tag.subject_id == subject.id)
        )
        print(
            f"[tags] status={tag_result.status} created={tag_result.created} "
            f"skipped={tag_result.skipped} failed={tag_result.failed} "
            f"total_before={before_tags} total_after={after_tags}"
        )
        for err in tag_result.errors:
            print(f"[tags][error] row={err.row} {err.message}")

        before_kps = await db.scalar(
            select(func.count(KnowledgePoint.id)).where(
                KnowledgePoint.subject_id == subject.id
            )
        )
        kp_result = await kp_import_service.import_excel(
            db,
            file_bytes=_build_kp_xlsx(),
            mode="incremental",
            user_id=1,
        )
        after_kps = await db.scalar(
            select(func.count(KnowledgePoint.id)).where(
                KnowledgePoint.subject_id == subject.id
            )
        )
        print(
            f"[kps] status={kp_result.status} created={kp_result.created} "
            f"skipped={kp_result.skipped} failed={kp_result.failed} "
            f"total_before={before_kps} total_after={after_kps}"
        )
        for err in kp_result.errors:
            print(f"[kps][error] row={err.row} {err.message}")

        # Integrity checks: category count + duplicate names per parent.
        categories = await db.scalar(
            select(func.count(KnowledgePoint.id)).where(
                KnowledgePoint.subject_id == subject.id,
                KnowledgePoint.name.in_(list(KP_TREE.keys())),
            )
        )
        dup_rows = await db.execute(
            select(
                KnowledgePoint.parent_id,
                KnowledgePoint.name,
                func.count(KnowledgePoint.id).label("c"),
            )
            .where(KnowledgePoint.subject_id == subject.id)
            .group_by(KnowledgePoint.parent_id, KnowledgePoint.name)
            .having(func.count(KnowledgePoint.id) > 1)
        )
        dups = dup_rows.all()
        print(f"[check] category_nodes={categories} duplicate_name_groups={len(dups)}")
        for parent_id, name, count in dups:
            print(f"[check][dup] parent={parent_id} name={name} count={count}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
