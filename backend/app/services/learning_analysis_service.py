"""Learning analysis services (admin / subject manager only).

Design:
- ``learning_attempts`` is the single source of truth for statistics.
- ``learning_wrong_stats`` and ``learning_review_schedules`` are derived caches
  refreshed in the same transaction as an attempt.
- No student account, no AI grading, no AI recommendation.  AI is used only to
  parse natural-language import text into candidates.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.crud_system_setting import system_setting
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question, question_knowledge_points
from app.models.subject import Subject
from app.models.system_setting import SystemSetting
from app.models.taxonomy import TaxonomyPrerequisite, TaxonomyTopicStandard
from app.models.learning_analysis import (
    LearningAttempt,
    LearningImportBatch,
    LearningReviewSchedule,
    LearningSession,
    LearningSessionItem,
    LearningStudent,
    LearningWrongStat,
)
from app.services.activity_logger import log_activity
from app.services.question_content import parse_json_field

ERROR_REASONS = (
    "概念不清",
    "公式记忆错误",
    "方法不会",
    "计算错误",
    "审题错误",
    "思路错误",
    "知识点混淆",
    "表达不规范",
    "粗心失误",
    "综合应用困难",
    "其他",
)
RESULT_VALUES = ("correct", "wrong", "partial")
CONFIG_KEY = "LEARNING_ANALYSIS_CONFIG"
DEFAULT_CONFIG = {
    "partial_weight": 0.5,
    "review_intervals": [1, 3, 7, 14, 30],
    "mastery_min_samples": 3,
    "mastery_thresholds": {"weak": 0.4, "learning": 0.65, "basic": 0.85},
    "default_recommendation_status": "published",
}
MASTERY_LABELS = ("unassessed", "weak", "learning", "basic", "mastered")
STAGE_NAMES = {
    1: "基础补弱",
    2: "核心巩固",
    3: "变式训练",
    4: "综合检测",
}
STAGE_DIFFICULTY = {1: (1, 2), 2: (2, 3), 3: (3, 4), 4: (4, 5)}


class LearningError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_dt(value: Any) -> datetime:
    if value is None or value == "":
        return _now()
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    raise LearningError(f"invalid datetime: {value}")


def _normalize_reasons(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [item.strip() for item in re.split(r"[,，;；/、\n]+", str(value))]
    reasons = []
    for item in items:
        if not item:
            continue
        if item not in ERROR_REASONS:
            raise LearningError(f"未知错误原因: {item}")
        if item not in reasons:
            reasons.append(item)
    return reasons


async def get_config(db: AsyncSession) -> dict[str, Any]:
    setting = await system_setting.get_by_key(db, CONFIG_KEY)
    if not setting or not setting.value:
        return dict(DEFAULT_CONFIG)
    try:
        stored = json.loads(setting.value)
    except (TypeError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    config = {**DEFAULT_CONFIG, **stored}
    intervals = [int(x) for x in config.get("review_intervals") or [] if int(x) > 0]
    config["review_intervals"] = intervals or DEFAULT_CONFIG["review_intervals"]
    config["partial_weight"] = min(1.0, max(0.0, float(config.get("partial_weight", 0.5))))
    return config


async def update_config(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    current = await get_config(db)
    merged = {**current, **{k: v for k, v in payload.items() if k in current}}
    setting = await system_setting.get_by_key(db, CONFIG_KEY)
    if setting is None:
        setting = SystemSetting(key=CONFIG_KEY, description="学习分析配置")
        db.add(setting)
    setting.value = json.dumps(merged, ensure_ascii=False)
    await db.commit()
    return merged


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


async def get_subject(db: AsyncSession, subject_id: int) -> Subject:
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise LearningError("subject not found", status_code=404)
    return subject


async def list_students(
    db: AsyncSession,
    *,
    subject_id: int,
    search: str | None = None,
    grade: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conditions = [LearningStudent.subject_id == subject_id]
    if search:
        conditions.append(LearningStudent.name.ilike(f"%{search}%"))
    if grade is not None:
        conditions.append(LearningStudent.grade == grade)
    rows = (
        await db.execute(
            select(LearningStudent)
            .where(*conditions)
            .order_by(LearningStudent.grade, LearningStudent.name, LearningStudent.id)
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    return [_student_dict(row) for row in rows]


def _student_dict(row: LearningStudent) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_id": row.subject_id,
        "name": row.name,
        "grade": row.grade,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create_student(
    db: AsyncSession, *, subject_id: int, name: str, grade: int, user_id: int | None
) -> dict[str, Any]:
    await get_subject(db, subject_id)
    if not name.strip():
        raise LearningError("学生姓名不能为空")
    if not 1 <= int(grade) <= 12:
        raise LearningError("年级必须在 1-12 之间")
    row = LearningStudent(subject_id=subject_id, name=name.strip(), grade=int(grade), created_by=user_id)
    db.add(row)
    await db.flush()
    await log_activity(db, user_id, "create", "learning_student", row.id, {"subject_id": subject_id, "name": row.name})
    await db.commit()
    await db.refresh(row)
    return _student_dict(row)


async def get_student(db: AsyncSession, *, subject_id: int, student_id: int) -> LearningStudent:
    row = (
        await db.execute(
            select(LearningStudent).where(
                LearningStudent.id == student_id, LearningStudent.subject_id == subject_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LearningError("student not found", status_code=404)
    return row


async def update_student(
    db: AsyncSession, *, subject_id: int, student_id: int, name: str | None, grade: int | None, user_id: int | None
) -> dict[str, Any]:
    row = await get_student(db, subject_id=subject_id, student_id=student_id)
    if name is not None:
        if not name.strip():
            raise LearningError("学生姓名不能为空")
        row.name = name.strip()
    if grade is not None:
        if not 1 <= int(grade) <= 12:
            raise LearningError("年级必须在 1-12 之间")
        row.grade = int(grade)
    await log_activity(db, user_id, "update", "learning_student", row.id, {"name": row.name, "grade": row.grade})
    await db.commit()
    await db.refresh(row)
    return _student_dict(row)


async def delete_student(db: AsyncSession, *, subject_id: int, student_id: int, user_id: int | None) -> dict[str, Any]:
    row = await get_student(db, subject_id=subject_id, student_id=student_id)
    await log_activity(db, user_id, "delete", "learning_student", row.id, {"subject_id": subject_id, "name": row.name})
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "student_id": student_id}


# ---------------------------------------------------------------------------
# Attempts and wrong stats
# ---------------------------------------------------------------------------


async def _get_question(db: AsyncSession, *, subject_id: int, question_id: int) -> Question:
    question = await db.get(Question, question_id)
    if question is None or question.deleted_at is not None:
        raise LearningError("question not found", status_code=404)
    if question.subject_id is not None and question.subject_id != subject_id:
        raise LearningError("question belongs to another subject", status_code=403)
    return question


async def _create_attempt_core(
    db: AsyncSession,
    *,
    subject_id: int,
    student: LearningStudent,
    question: Question,
    result: str,
    error_reasons: Iterable[str] | None,
    note: str | None,
    answered_at: datetime,
    source: str,
    session_id: int | None,
    user_id: int | None,
    config: dict[str, Any],
) -> LearningAttempt:
    if result not in RESULT_VALUES:
        raise LearningError("result must be correct/wrong/partial")
    reasons = list(error_reasons or [])
    attempt = LearningAttempt(
        subject_id=subject_id,
        student_id=student.id,
        question_id=question.id,
        session_id=session_id,
        result=result,
        error_reasons=reasons or None,
        note=note,
        answered_at=answered_at,
        source=source,
        created_by=user_id,
    )
    db.add(attempt)
    await db.flush()

    if result in {"wrong", "partial"}:
        stat = (
            await db.execute(
                select(LearningWrongStat).where(
                    LearningWrongStat.student_id == student.id,
                    LearningWrongStat.question_id == question.id,
                )
            )
        ).scalar_one_or_none()
        if stat is None:
            stat = LearningWrongStat(
                subject_id=subject_id,
                student_id=student.id,
                question_id=question.id,
                wrong_count=0,
                partial_count=0,
            )
            db.add(stat)
        if result == "wrong":
            stat.wrong_count += 1
        else:
            stat.partial_count += 1
        stat.last_wrong_at = answered_at
        if reasons:
            stat.error_reasons = reasons
        if note:
            stat.note = note

    await _update_review_schedule(
        db,
        subject_id=subject_id,
        student_id=student.id,
        question_id=question.id,
        result=result,
        at=answered_at,
        config=config,
    )
    return attempt


async def create_attempt(
    db: AsyncSession,
    *,
    subject_id: int,
    student_id: int,
    question_id: int,
    result: str,
    error_reasons: Any = None,
    note: str | None = None,
    answered_at: Any = None,
    source: str = "manual",
    session_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    student = await get_student(db, subject_id=subject_id, student_id=student_id)
    question = await _get_question(db, subject_id=subject_id, question_id=question_id)
    if session_id is not None:
        session = await get_session(db, subject_id=subject_id, session_id=session_id)
        if session.student_id != student.id:
            raise LearningError("session belongs to another student", status_code=403)
    reasons = _normalize_reasons(error_reasons)
    config = await get_config(db)
    attempt = await _create_attempt_core(
        db,
        subject_id=subject_id,
        student=student,
        question=question,
        result=result,
        error_reasons=reasons,
        note=note,
        answered_at=_parse_dt(answered_at),
        source=source,
        session_id=session_id,
        user_id=user_id,
        config=config,
    )
    await log_activity(db, user_id, "create", "learning_attempt", attempt.id, {"student_id": student.id, "question_id": question.id, "result": result})
    await db.commit()
    await db.refresh(attempt)
    return _attempt_dict(attempt)


def _attempt_dict(row: LearningAttempt) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_id": row.subject_id,
        "student_id": row.student_id,
        "question_id": row.question_id,
        "session_id": row.session_id,
        "result": row.result,
        "error_reasons": row.error_reasons or [],
        "note": row.note,
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
        "source": row.source,
    }


async def list_attempts(
    db: AsyncSession,
    *,
    subject_id: int,
    student_id: int | None = None,
    question_id: int | None = None,
    result: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conditions = [LearningAttempt.subject_id == subject_id]
    if student_id is not None:
        await get_student(db, subject_id=subject_id, student_id=student_id)
        conditions.append(LearningAttempt.student_id == student_id)
    if question_id is not None:
        conditions.append(LearningAttempt.question_id == question_id)
    if result:
        conditions.append(LearningAttempt.result == result)
    rows = (
        await db.execute(
            select(LearningAttempt)
            .where(*conditions)
            .order_by(LearningAttempt.answered_at.desc(), LearningAttempt.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_attempt_dict(row) for row in rows]


async def list_wrong_questions(
    db: AsyncSession, *, subject_id: int, student_id: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    conditions = [LearningWrongStat.subject_id == subject_id]
    if student_id is not None:
        await get_student(db, subject_id=subject_id, student_id=student_id)
        conditions.append(LearningWrongStat.student_id == student_id)
    rows = (
        await db.execute(
            select(LearningWrongStat, Question)
            .join(Question, Question.id == LearningWrongStat.question_id)
            .where(*conditions, Question.deleted_at.is_(None))
            .order_by(LearningWrongStat.last_wrong_at.desc(), LearningWrongStat.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": stat.id,
            "student_id": stat.student_id,
            "question_id": stat.question_id,
            "wrong_count": stat.wrong_count,
            "partial_count": stat.partial_count,
            "total_error_count": stat.wrong_count + stat.partial_count,
            "last_wrong_at": stat.last_wrong_at.isoformat() if stat.last_wrong_at else None,
            "error_reasons": stat.error_reasons or [],
            "note": stat.note,
            "question": {
                "id": question.id,
                "q_type": question.q_type.value if hasattr(question.q_type, "value") else str(question.q_type),
                "difficulty": question.difficulty,
                "status": question.status,
                "content": question.content,
            },
        }
        for stat, question in rows
    ]


# ---------------------------------------------------------------------------
# Review schedule
# ---------------------------------------------------------------------------


async def _update_review_schedule(
    db: AsyncSession,
    *,
    subject_id: int,
    student_id: int,
    question_id: int,
    result: str,
    at: datetime,
    config: dict[str, Any],
) -> None:
    schedule = (
        await db.execute(
            select(LearningReviewSchedule).where(
                LearningReviewSchedule.student_id == student_id,
                LearningReviewSchedule.question_id == question_id,
            )
        )
    ).scalar_one_or_none()
    intervals = config["review_intervals"]
    if schedule is None:
        schedule = LearningReviewSchedule(
            subject_id=subject_id,
            student_id=student_id,
            question_id=question_id,
            due_at=at + timedelta(days=intervals[0]),
            interval_days=intervals[0],
            repetitions=0,
            lapses=0,
            status="scheduled",
        )
        db.add(schedule)
    if result == "wrong":
        schedule.repetitions = 0
        schedule.lapses += 1
        schedule.interval_days = intervals[0]
        schedule.due_at = at + timedelta(days=intervals[0])
        schedule.status = "scheduled"
    elif result == "partial":
        schedule.repetitions = max(0, schedule.repetitions)
        schedule.interval_days = intervals[0]
        schedule.due_at = at + timedelta(days=intervals[0])
        schedule.status = "scheduled"
    else:
        schedule.repetitions += 1
        index = min(schedule.repetitions - 1, len(intervals) - 1)
        schedule.interval_days = intervals[index]
        schedule.due_at = at + timedelta(days=schedule.interval_days)
        schedule.status = "scheduled"
    schedule.last_result = result


async def list_reviews(
    db: AsyncSession, *, subject_id: int, student_id: int | None = None, due_only: bool = False, limit: int = 200
) -> list[dict[str, Any]]:
    conditions = [LearningReviewSchedule.subject_id == subject_id]
    if student_id is not None:
        await get_student(db, subject_id=subject_id, student_id=student_id)
        conditions.append(LearningReviewSchedule.student_id == student_id)
    if due_only:
        conditions.append(LearningReviewSchedule.due_at <= _now())
    rows = (
        await db.execute(
            select(LearningReviewSchedule)
            .where(*conditions)
            .order_by(LearningReviewSchedule.due_at)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "student_id": row.student_id,
            "question_id": row.question_id,
            "due_at": row.due_at.isoformat(),
            "interval_days": row.interval_days,
            "repetitions": row.repetitions,
            "lapses": row.lapses,
            "last_result": row.last_result,
            "status": row.status,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Mastery
# ---------------------------------------------------------------------------


def _mastery_status(score: float, samples: int, config: dict[str, Any]) -> str:
    if samples < int(config["mastery_min_samples"]):
        return "unassessed"
    t = config["mastery_thresholds"]
    if score >= t["basic"]:
        return "mastered"
    if score >= t["learning"]:
        return "basic"
    if score >= t["weak"]:
        return "learning"
    return "weak"


async def compute_mastery(
    db: AsyncSession, *, subject_id: int, student_id: int, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    await get_student(db, subject_id=subject_id, student_id=student_id)
    config = config or await get_config(db)
    weight = float(config["partial_weight"])
    rows = (
        await db.execute(
            select(
                KnowledgePoint.id,
                KnowledgePoint.name,
                LearningAttempt.result,
                func.count(LearningAttempt.id),
            )
            .select_from(LearningAttempt)
            .join(
                question_knowledge_points,
                question_knowledge_points.c.question_id == LearningAttempt.question_id,
            )
            .join(
                KnowledgePoint,
                KnowledgePoint.id == question_knowledge_points.c.knowledge_point_id,
            )
            .where(
                LearningAttempt.subject_id == subject_id,
                LearningAttempt.student_id == student_id,
            )
            .group_by(KnowledgePoint.id, KnowledgePoint.name, LearningAttempt.result)
        )
    ).all()
    aggregated: dict[int, dict[str, Any]] = {}
    for kp_id, name, result, count in rows:
        entry = aggregated.setdefault(
            kp_id, {"knowledge_point_id": kp_id, "name": name, "attempts": 0, "correct": 0, "wrong": 0, "partial": 0}
        )
        entry["attempts"] += int(count)
        entry[result] += int(count)
    for entry in aggregated.values():
        score = (entry["correct"] + entry["partial"] * weight) / entry["attempts"] if entry["attempts"] else 0.0
        entry["score"] = round(score, 4)
        entry["status"] = _mastery_status(score, entry["attempts"], config)
    return {
        "student_id": student_id,
        "partial_weight": weight,
        "knowledge_points": sorted(aggregated.values(), key=lambda item: (item["score"], item["knowledge_point_id"])),
    }


async def compute_type_mastery(
    db: AsyncSession, *, subject_id: int, student_id: int, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    await get_student(db, subject_id=subject_id, student_id=student_id)
    config = config or await get_config(db)
    weight = float(config["partial_weight"])
    rows = (
        await db.execute(
            select(Question.q_type, LearningAttempt.result, func.count(LearningAttempt.id))
            .join(Question, Question.id == LearningAttempt.question_id)
            .where(LearningAttempt.subject_id == subject_id, LearningAttempt.student_id == student_id)
            .group_by(Question.q_type, LearningAttempt.result)
        )
    ).all()
    grouped: dict[str, dict[str, Any]] = {}
    for q_type, result, count in rows:
        key = q_type.value if hasattr(q_type, "value") else str(q_type)
        entry = grouped.setdefault(key, {"q_type": key, "attempts": 0, "correct": 0, "wrong": 0, "partial": 0})
        entry["attempts"] += int(count)
        entry[result] += int(count)
    for entry in grouped.values():
        score = (entry["correct"] + entry["partial"] * weight) / entry["attempts"] if entry["attempts"] else 0.0
        entry["score"] = round(score, 4)
        entry["status"] = _mastery_status(score, entry["attempts"], config)
    return sorted(grouped.values(), key=lambda item: item["q_type"])


# ---------------------------------------------------------------------------
# Recommendations / sessions
# ---------------------------------------------------------------------------


async def _latest_attempt_results(
    db: AsyncSession, *, subject_id: int, student_id: int
) -> dict[int, str]:
    """Return the latest result per question for one student.

    ``exclude_practiced`` should only remove questions the student has most
    recently answered correctly.  Wrong/partial answers stay eligible so the
    wrong-question recommendation loop can actually re-practice them.
    """
    rows = (
        await db.execute(
            select(LearningAttempt.question_id, LearningAttempt.result)
            .where(
                LearningAttempt.subject_id == subject_id,
                LearningAttempt.student_id == student_id,
            )
            .order_by(
                LearningAttempt.question_id,
                LearningAttempt.answered_at.desc(),
                LearningAttempt.id.desc(),
            )
        )
    ).all()
    latest: dict[int, str] = {}
    for question_id, result in rows:
        latest.setdefault(question_id, result)
    return latest


async def recommend_questions(
    db: AsyncSession,
    *,
    subject_id: int,
    student_id: int,
    knowledge_point_ids: list[int] | None = None,
    question_ids: list[int] | None = None,
    mode: str = "recommendation",
    stage: int | None = None,
    limit: int = 10,
    include_unpublished: bool = False,
    exclude_practiced: bool = True,
) -> dict[str, Any]:
    student = await get_student(db, subject_id=subject_id, student_id=student_id)
    config = await get_config(db)
    if mode == "four_stage" and stage not in STAGE_NAMES:
        raise LearningError("stage must be 1-4 for four_stage")
    conditions = [Question.subject_id == subject_id, Question.deleted_at.is_(None)]
    if not include_unpublished:
        conditions.append(Question.status == "published")
    if question_ids:
        conditions.append(Question.id.in_(question_ids))
    if knowledge_point_ids:
        conditions.append(
            Question.id.in_(
                select(Question.id)
                .join(Question.knowledge_points)
                .where(KnowledgePoint.id.in_(knowledge_point_ids))
            )
        )
    if mode == "four_stage" and stage:
        low, high = STAGE_DIFFICULTY[stage]
        conditions.extend([Question.difficulty >= low, Question.difficulty <= high])
    rows = (
        await db.execute(
            select(Question).where(*conditions).order_by(Question.difficulty, Question.id).limit(500)
        )
    ).scalars().all()
    if not rows:
        reason = (
            "no_published_questions" if not include_unpublished else "no_available_questions"
        )
        return {"items": [], "reason": reason, "student_id": student_id, "mode": mode, "stage": stage}

    latest_results = (
        await _latest_attempt_results(db, subject_id=subject_id, student_id=student_id)
        if exclude_practiced
        else {}
    )
    # Only questions most recently answered correctly are de-duplicated.
    practiced = {qid for qid, result in latest_results.items() if result == "correct"}
    wrong_rows = (
        await db.execute(
            select(LearningWrongStat.question_id)
            .where(LearningWrongStat.subject_id == subject_id, LearningWrongStat.student_id == student_id)
            .order_by(LearningWrongStat.last_wrong_at.desc())
        )
    ).scalars().all()
    wrong_ids = set(wrong_rows)
    mastery = await compute_mastery(db, subject_id=subject_id, student_id=student_id, config=config)
    weak_kp_ids = {item["knowledge_point_id"] for item in mastery["knowledge_points"] if item["status"] in {"weak", "learning"}}
    prerequisite_kp_ids = set()
    if weak_kp_ids:
        prerequisite_kp_ids = set(
            (
                await db.execute(
                    select(TaxonomyPrerequisite.prerequisite_knowledge_point_id).where(
                        TaxonomyPrerequisite.knowledge_point_id.in_(weak_kp_ids),
                        TaxonomyPrerequisite.is_current.is_(True),
                    )
                )
            ).scalars().all()
        )
    target_kps = set(knowledge_point_ids or []) | weak_kp_ids | prerequisite_kp_ids
    wrong_types = {
        q_type
        for (q_type,) in (
            await db.execute(
                select(Question.q_type)
                .join(LearningAttempt, LearningAttempt.question_id == Question.id)
                .where(
                    LearningAttempt.subject_id == subject_id,
                    LearningAttempt.student_id == student_id,
                    LearningAttempt.result.in_(["wrong", "partial"]),
                )
                .distinct()
            )
        ).all()
    }
    question_ids_all = [question.id for question in rows]
    kp_map: dict[int, set[int]] = {}
    if question_ids_all:
        links = (
            await db.execute(
                select(
                    question_knowledge_points.c.question_id,
                    question_knowledge_points.c.knowledge_point_id,
                ).where(question_knowledge_points.c.question_id.in_(question_ids_all))
            )
        ).all()
        for question_id, knowledge_point_id in links:
            kp_map.setdefault(question_id, set()).add(knowledge_point_id)
    kp_name_map: dict[int, str] = {}
    all_kp_ids = {kp_id for ids in kp_map.values() for kp_id in ids}
    if all_kp_ids:
        kp_rows = (
            await db.execute(
                select(KnowledgePoint.id, KnowledgePoint.name).where(
                    KnowledgePoint.id.in_(all_kp_ids)
                )
            )
        ).all()
        kp_name_map = {kp_id: name for kp_id, name in kp_rows}
    items = []
    for question in rows:
        if exclude_practiced and question.id in practiced:
            continue
        kp_ids = kp_map.get(question.id, set())
        reasons = []
        score = 0.0
        if question.id in wrong_ids:
            reasons.append("错题/部分正确历史")
            score += 10
        if kp_ids & weak_kp_ids:
            reasons.append("薄弱知识点")
            score += 5
        if kp_ids & prerequisite_kp_ids:
            reasons.append("先修知识点补强")
            score += 3
        if question.q_type in wrong_types:
            reasons.append("同题型强化")
            score += 2
        if not reasons:
            reasons.append("常规推荐")
        items.append(
            {
                "question_id": question.id,
                "q_type": question.q_type.value if hasattr(question.q_type, "value") else str(question.q_type),
                "difficulty": question.difficulty,
                "status": question.status,
                "knowledge_point_ids": sorted(kp_ids),
                "knowledge_points": [
                    {"id": kp_id, "name": kp_name_map.get(kp_id, "")}
                    for kp_id in sorted(kp_ids)
                ],
                "content": parse_json_field(question.content),
                "options": question.options or [],
                "answer": parse_json_field(question.answer),
                "thinking": parse_json_field(question.thinking),
                "analysis": parse_json_field(question.analysis),
                "reasons": reasons,
                "score": score,
            }
        )
    items.sort(key=lambda item: (-item["score"], item["difficulty"], item["question_id"]))
    selected = items[: max(1, min(int(limit), 100))]
    if not selected:
        return {
            "items": [],
            "reason": "all_candidates_already_practiced" if exclude_practiced else "no_available_questions",
            "student_id": student_id,
            "mode": mode,
            "stage": stage,
        }
    return {
        "items": selected,
        "reason": None,
        "student_id": student_id,
        "mode": mode,
        "stage": stage,
        "include_unpublished": include_unpublished,
        "stage_name": STAGE_NAMES.get(stage) if stage else None,
    }


async def create_session(
    db: AsyncSession,
    *,
    subject_id: int,
    student_id: int,
    question_ids: list[int],
    mode: str = "recommendation",
    stage: int | None = None,
    title: str | None = None,
    reasons: dict[int, list[str]] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    await get_student(db, subject_id=subject_id, student_id=student_id)
    if not question_ids:
        raise LearningError("question_ids cannot be empty")
    questions = (
        await db.execute(
            select(Question).where(
                Question.id.in_(question_ids),
                Question.subject_id == subject_id,
                Question.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    found = {q.id: q for q in questions}
    missing = [qid for qid in question_ids if qid not in found]
    if missing:
        raise LearningError(f"questions not found in subject: {missing[:5]}")
    session = LearningSession(
        subject_id=subject_id,
        student_id=student_id,
        mode=mode,
        stage=stage,
        status="active",
        title=title,
        created_by=user_id,
    )
    db.add(session)
    await db.flush()
    seen = set()
    for index, qid in enumerate(question_ids):
        if qid in seen:
            continue
        seen.add(qid)
        db.add(
            LearningSessionItem(
                session_id=session.id,
                question_id=qid,
                sequence=index,
                stage=stage,
                reason={"reasons": (reasons or {}).get(qid, [])},
            )
        )
    await db.commit()
    await db.refresh(session)
    return await get_session(db, subject_id=subject_id, session_id=session.id)


async def get_session(db: AsyncSession, *, subject_id: int, session_id: int) -> Any:
    session = (
        await db.execute(
            select(LearningSession).where(
                LearningSession.id == session_id, LearningSession.subject_id == subject_id
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise LearningError("session not found", status_code=404)
    items = (
        await db.execute(
            select(LearningSessionItem, Question)
            .join(Question, Question.id == LearningSessionItem.question_id)
            .where(LearningSessionItem.session_id == session.id)
            .order_by(LearningSessionItem.sequence)
        )
    ).all()
    return {
        "id": session.id,
        "subject_id": session.subject_id,
        "student_id": session.student_id,
        "mode": session.mode,
        "stage": session.stage,
        "status": session.status,
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "items": [
            {
                "id": item.id,
                "question_id": item.question_id,
                "sequence": item.sequence,
                "stage": item.stage,
                "reason": item.reason,
                "q_type": question.q_type.value if hasattr(question.q_type, "value") else str(question.q_type),
                "difficulty": question.difficulty,
                "status": question.status,
                "content": question.content,
            }
            for item, question in items
        ],
    }


async def list_sessions(
    db: AsyncSession, *, subject_id: int, student_id: int | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    conditions = [LearningSession.subject_id == subject_id]
    if student_id is not None:
        await get_student(db, subject_id=subject_id, student_id=student_id)
        conditions.append(LearningSession.student_id == student_id)
    rows = (
        await db.execute(
            select(LearningSession)
            .where(*conditions)
            .order_by(LearningSession.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "student_id": row.student_id,
            "mode": row.mode,
            "stage": row.stage,
            "status": row.status,
            "title": row.title,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Imports (Excel/CSV + natural language)
# ---------------------------------------------------------------------------

IMPORT_COLUMNS = ["学生姓名", "年级", "学科", "题目ID", "错误原因", "备注", "错误时间"]


def build_import_template() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "错题导入"
    ws.append(IMPORT_COLUMNS)
    ws.append(["张三", 9, "数学", 1, "计算错误,粗心失误", "示例备注", "2026-01-01 10:00"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _read_import_rows(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    import pandas as pd

    if filename.lower().endswith(".csv"):
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding="gb18030")
    elif filename.lower().endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    else:
        raise LearningError("仅支持 .xlsx 或 .csv")
    missing = [col for col in IMPORT_COLUMNS if col not in df.columns]
    if missing:
        raise LearningError(f"缺少列: {', '.join(missing)}")
    rows = []
    for index, row in df.iterrows():
        rows.append(
            {
                "row": int(index) + 2,
                **{col: (None if pd.isna(row[col]) else str(row[col]).strip()) for col in IMPORT_COLUMNS},
            }
        )
    return rows


async def _match_import_rows(
    db: AsyncSession, *, subject_id: int, subject: Subject, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    students = (
        await db.execute(select(LearningStudent).where(LearningStudent.subject_id == subject_id))
    ).scalars().all()
    student_map: dict[tuple[str, int], list[LearningStudent]] = {}
    for student in students:
        student_map.setdefault((student.name.strip(), int(student.grade)), []).append(student)
    question_ids = set()
    for row in rows:
        try:
            question_ids.add(int(row.get("题目ID") or 0))
        except (TypeError, ValueError):
            pass
    questions = (
        await db.execute(
            select(Question).where(
                Question.id.in_(question_ids),
                Question.subject_id == subject_id,
                Question.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    question_map = {question.id: question for question in questions}
    results = []
    seen = set()
    for row in rows:
        errors = []
        name = (row.get("学生姓名") or "").strip()
        grade = row.get("年级")
        subject_value = (row.get("学科") or "").strip()
        question_id = row.get("题目ID")
        try:
            grade_int = int(str(grade))
        except (TypeError, ValueError):
            grade_int = 0
            errors.append("年级无效")
        if not name:
            errors.append("学生姓名为空")
        if subject_value and subject_value not in {str(subject.id), subject.name, subject.slug}:
            errors.append("学科不匹配")
        try:
            question_id_int = int(str(question_id))
        except (TypeError, ValueError):
            question_id_int = 0
            errors.append("题目ID无效")
        matches = student_map.get((name, grade_int), [])
        if not name or grade_int <= 0:
            pass
        elif len(matches) == 0:
            errors.append("未找到学生（姓名+年级）")
        elif len(matches) > 1:
            errors.append("学生匹配不唯一，请手动确认")
        question = question_map.get(question_id_int)
        if question_id_int and question is None:
            errors.append("未找到题目或题目不属于本学科")
        if (name, grade_int, question_id_int) in seen:
            errors.append("文件内重复行")
        seen.add((name, grade_int, question_id_int))
        try:
            reasons = _normalize_reasons(row.get("错误原因"))
        except LearningError as exc:
            reasons = []
            errors.append(exc.message)
        answered_at = row.get("错误时间") or None
        parsed_at = None
        if answered_at:
            try:
                parsed_at = _parse_dt(answered_at)
            except LearningError:
                errors.append("错误时间格式无效")
        results.append(
            {
                "row": row["row"],
                "student_id": matches[0].id if len(matches) == 1 else None,
                "student_name": name,
                "grade": grade_int or None,
                "question_id": question_id_int or None,
                "error_reasons": reasons,
                "note": row.get("备注") or None,
                "answered_at": (parsed_at.isoformat() if parsed_at else None),
                "status": "error" if errors else "ready",
                "errors": errors,
            }
        )
    return results


async def preview_import_rows(
    db: AsyncSession,
    *,
    subject_id: int,
    rows: list[dict[str, Any]],
    kind: str,
    content_hash: str,
    user_id: int | None,
) -> dict[str, Any]:
    subject = await get_subject(db, subject_id)
    matched = await _match_import_rows(db, subject_id=subject_id, subject=subject, rows=rows)
    ok = sum(1 for row in matched if row["status"] == "ready")
    duplicate = (
        await db.execute(
            select(LearningImportBatch)
            .where(
                LearningImportBatch.subject_id == subject_id,
                LearningImportBatch.kind == kind,
                LearningImportBatch.status == "committed",
                LearningImportBatch.content_hash == content_hash,
            )
            .order_by(LearningImportBatch.id.desc())
        )
    ).scalars().first()
    batch = LearningImportBatch(
        subject_id=subject_id,
        kind=kind,
        status="preview",
        content_hash=content_hash,
        payload={"rows": matched},
        summary={
            "total": len(matched),
            "ready": ok,
            "errors": len(matched) - ok,
            "duplicate_of_batch_id": duplicate.id if duplicate else None,
        },
        created_by=user_id,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return {"batch_id": batch.id, "rows": matched, "summary": batch.summary}


async def preview_excel_import(
    db: AsyncSession, *, subject_id: int, file_bytes: bytes, filename: str, user_id: int | None
) -> dict[str, Any]:
    rows = _read_import_rows(file_bytes, filename)
    if len(rows) > 1000:
        raise LearningError("单次最多导入 1000 行")
    return await preview_import_rows(
        db,
        subject_id=subject_id,
        rows=rows,
        kind="excel",
        content_hash=hashlib.sha256(file_bytes).hexdigest(),
        user_id=user_id,
    )


async def preview_nl_import(
    db: AsyncSession, *, subject_id: int, text: str, user_id: int | None
) -> dict[str, Any]:
    if not text.strip():
        raise LearningError("请输入要解析的文本")
    if len(text) > 20000:
        raise LearningError("文本过长（最多 20000 字符）")
    parsed = await _parse_nl_rows(db, text)
    rows = [
        {
            "row": index + 1,
            "学生姓名": item.get("student_name"),
            "年级": item.get("grade"),
            "学科": item.get("subject") or "",
            "题目ID": item.get("question_id"),
            "错误原因": item.get("error_reasons") or "",
            "备注": item.get("note") or "",
            "错误时间": item.get("answered_at") or "",
        }
        for index, item in enumerate(parsed)
    ]
    if not rows:
        raise LearningError("AI 未解析出任何错题记录")
    return await preview_import_rows(
        db,
        subject_id=subject_id,
        rows=rows,
        kind="nl",
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        user_id=user_id,
    )


async def _parse_nl_rows(db: AsyncSession, text: str) -> list[dict[str, Any]]:
    from app.services.ai_provider import get_ai_provider
    from app.services.importing.provider_config import resolve_active_provider

    provider_name, config = await resolve_active_provider(db, is_vision=False)
    if provider_name is None:
        raise LearningError("未配置激活的文本 AI 模型", status_code=400)
    provider = get_ai_provider(provider_name)
    prompt = (
        "你是数据整理助手。把用户提供的错题记录解析为 JSON 数组，每项字段："
        "student_name(字符串), grade(整数), subject(字符串), question_id(整数), "
        "error_reasons(字符串数组), note(字符串), answered_at(字符串或空)。"
        f"错误原因只能取: {', '.join(ERROR_REASONS)}。"
        "只输出 JSON 数组，不要解释、不要 markdown 代码块。"
        "无法确定的字段留空，不要猜测题目 ID。"
    )
    chunks = []
    try:
        async for chunk in provider.chat_stream(
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            config,
        ):
            if isinstance(chunk, str):
                chunks.append(chunk)
    except Exception as exc:
        raise LearningError(
            f"AI 调用失败（{type(exc).__name__}），请稍后重试"
        ) from exc
    raw = "".join(chunks).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LearningError(f"AI 返回不是合法 JSON: {exc}") from exc
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("records") or []
    if not isinstance(payload, list):
        raise LearningError("AI 返回结构不是数组")
    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            question_id = int(item.get("question_id")) if item.get("question_id") not in (None, "") else None
        except (TypeError, ValueError):
            question_id = None
        try:
            grade = int(item.get("grade")) if item.get("grade") not in (None, "") else None
        except (TypeError, ValueError):
            grade = None
        result.append(
            {
                "student_name": str(item.get("student_name") or "").strip(),
                "grade": grade,
                "subject": str(item.get("subject") or "").strip(),
                "question_id": question_id,
                "error_reasons": item.get("error_reasons") or [],
                "note": str(item.get("note") or "").strip(),
                "answered_at": item.get("answered_at"),
            }
        )
    return result


async def commit_import(
    db: AsyncSession, *, subject_id: int, batch_id: int, user_id: int | None
) -> dict[str, Any]:
    batch = (
        await db.execute(
            select(LearningImportBatch).where(
                LearningImportBatch.id == batch_id,
                LearningImportBatch.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise LearningError("import batch not found", status_code=404)
    if batch.status != "preview":
        raise LearningError("batch already committed", status_code=409)
    rows = (batch.payload or {}).get("rows") or []
    ready = [row for row in rows if row.get("status") == "ready"]
    if not ready:
        raise LearningError("没有可导入的行")
    config = await get_config(db)
    created = 0
    try:
        for row in ready:
            student = await get_student(db, subject_id=subject_id, student_id=int(row["student_id"]))
            question = await _get_question(db, subject_id=subject_id, question_id=int(row["question_id"]))
            await _create_attempt_core(
                db,
                subject_id=subject_id,
                student=student,
                question=question,
                result="wrong",
                error_reasons=row.get("error_reasons") or [],
                note=row.get("note"),
                answered_at=_parse_dt(row.get("answered_at")),
                source=f"import_{batch.kind}",
                session_id=None,
                user_id=user_id,
                config=config,
            )
            created += 1
        batch.status = "committed"
        batch.committed_at = _now()
        batch.summary = {**(batch.summary or {}), "created": created}
        await log_activity(db, user_id, "import", "learning_attempt", batch.id, {"batch_id": batch.id, "created": created})
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(batch)
    return {"batch_id": batch.id, "status": batch.status, "created": created, "summary": batch.summary}


async def import_errors_csv(
    db: AsyncSession, *, subject_id: int, batch_id: int
) -> bytes:
    batch = (
        await db.execute(
            select(LearningImportBatch).where(
                LearningImportBatch.id == batch_id,
                LearningImportBatch.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise LearningError("import batch not found", status_code=404)
    rows = (batch.payload or {}).get("rows") or []
    import csv

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["行", "学生", "年级", "题目ID", "状态", "错误"])
    for row in rows:
        if row.get("status") == "ready":
            continue
        writer.writerow([
            row.get("row"),
            row.get("student_name"),
            row.get("grade"),
            row.get("question_id"),
            row.get("status"),
            "; ".join(row.get("errors") or []),
        ])
    return out.getvalue().encode("utf-8-sig")


async def list_import_batches(
    db: AsyncSession, *, subject_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(LearningImportBatch)
            .where(LearningImportBatch.subject_id == subject_id)
            .order_by(LearningImportBatch.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "status": row.status,
            "summary": row.summary,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "committed_at": row.committed_at.isoformat() if row.committed_at else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Student report
# ---------------------------------------------------------------------------


async def student_report(
    db: AsyncSession, *, subject_id: int, student_id: int
) -> dict[str, Any]:
    student = await get_student(db, subject_id=subject_id, student_id=student_id)
    config = await get_config(db)
    attempts = await list_attempts(db, subject_id=subject_id, student_id=student_id, limit=1000)
    wrong = await list_wrong_questions(db, subject_id=subject_id, student_id=student_id, limit=500)
    mastery = await compute_mastery(db, subject_id=subject_id, student_id=student_id, config=config)
    type_mastery = await compute_type_mastery(db, subject_id=subject_id, student_id=student_id, config=config)
    reviews = await list_reviews(db, subject_id=subject_id, student_id=student_id, limit=200)
    sessions = await list_sessions(db, subject_id=subject_id, student_id=student_id, limit=50)
    counts = {"correct": 0, "wrong": 0, "partial": 0}
    for attempt in attempts:
        counts[attempt["result"]] = counts.get(attempt["result"], 0) + 1
    return {
        "student": _student_dict(student),
        "summary": {
            "attempts": len(attempts),
            **counts,
            "wrong_question_count": len(wrong),
            "total_error_count": sum(item["total_error_count"] for item in wrong),
            "last_wrong_at": wrong[0]["last_wrong_at"] if wrong else None,
            "partial_weight": config["partial_weight"],
        },
        "wrong_questions": wrong,
        "mastery": mastery,
        "type_mastery": type_mastery,
        "reviews": reviews,
        "sessions": sessions,
        "stage_names": STAGE_NAMES,
        "recommendations": (
            await recommend_questions(
                db,
                subject_id=subject_id,
                student_id=student_id,
                limit=10,
                include_unpublished=False,
            )
        )["items"],
    }
