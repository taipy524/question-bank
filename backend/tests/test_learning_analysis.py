import io

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.models.knowledge_point import KnowledgePoint
from app.models.learning_analysis import (
    LearningAttempt,
    LearningReviewSchedule,
    LearningStudent,
    LearningWrongStat,
)
from app.models.question import Question, QuestionType
from app.models.subject import Subject
from app.services import learning_analysis_service as service


async def _seed(db):
    subject = Subject(name="数学", slug="math-learning")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    kp1 = KnowledgePoint(name="一元二次方程", slug="kp-quadratic", subject_id=subject.id)
    kp2 = KnowledgePoint(name="二次函数", slug="kp-function", subject_id=subject.id)
    db.add_all([kp1, kp2])
    await db.commit()
    await db.refresh(kp1)
    await db.refresh(kp2)
    question = Question(
        content='{"type":"doc","content":[]}',
        q_type=QuestionType.SINGLE_CHOICE,
        status="published",
        difficulty=3,
        subject_id=subject.id,
    )
    question.knowledge_points.append(kp1)
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return subject, kp1, kp2, question


async def test_student_attempt_stats_and_mastery(db_session):
    subject, kp1, kp2, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="张三", grade=9, user_id=None
    )
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="wrong", error_reasons=["计算错误"], note="第一次",
    )
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="wrong", error_reasons=["思路错误"],
    )
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="partial", error_reasons=["表达不规范"],
    )
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="correct",
    )
    attempts = await service.list_attempts(db_session, subject_id=subject.id, student_id=student["id"])
    assert len(attempts) == 4
    wrong = await service.list_wrong_questions(db_session, subject_id=subject.id, student_id=student["id"])
    assert wrong[0]["wrong_count"] == 2
    assert wrong[0]["partial_count"] == 1
    mastery = await service.compute_mastery(db_session, subject_id=subject.id, student_id=student["id"])
    entry = mastery["knowledge_points"][0]
    assert entry["knowledge_point_id"] == kp1.id
    assert entry["attempts"] == 4
    assert entry["score"] == pytest.approx(0.375)
    assert entry["status"] == "weak"
    scheduled = (await db_session.execute(select(LearningReviewSchedule))).scalars().all()
    assert len(scheduled) == 1
    assert scheduled[0].last_result == "correct"


async def test_student_delete_cascades_learning_data(db_session):
    subject, _, _, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="李四", grade=9, user_id=None
    )
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="wrong", error_reasons=["概念不清"],
    )
    await service.delete_student(
        db_session, subject_id=subject.id, student_id=student["id"], user_id=None
    )
    assert (await db_session.execute(select(func.count()).select_from(LearningAttempt))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(LearningWrongStat))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(LearningReviewSchedule))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(LearningStudent))).scalar_one() == 0


async def test_recommendation_status_and_practiced_filter(db_session):
    subject, kp1, _, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="王五", grade=9, user_id=None
    )
    question.status = "pending"
    await db_session.commit()
    empty = await service.recommend_questions(
        db_session, subject_id=subject.id, student_id=student["id"]
    )
    assert empty["items"] == []
    assert empty["reason"] == "no_published_questions"
    pending = await service.recommend_questions(
        db_session, subject_id=subject.id, student_id=student["id"], include_unpublished=True
    )
    assert pending["items"][0]["question_id"] == question.id
    question.status = "published"
    await db_session.commit()
    filtered = await service.recommend_questions(
        db_session, subject_id=subject.id, student_id=student["id"], knowledge_point_ids=[kp1.id]
    )
    assert filtered["items"][0]["question_id"] == question.id
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="wrong", error_reasons=["计算错误"],
    )
    recommended = await service.recommend_questions(
        db_session, subject_id=subject.id, student_id=student["id"], exclude_practiced=True
    )
    assert recommended["items"] == []
    assert recommended["reason"] == "all_candidates_already_practiced"


async def test_four_stage_session(db_session):
    subject, kp1, _, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="赵六", grade=9, user_id=None
    )
    session = await service.create_session(
        db_session,
        subject_id=subject.id,
        student_id=student["id"],
        question_ids=[question.id],
        mode="four_stage",
        stage=2,
        reasons={question.id: ["核心巩固"]},
    )
    assert session["stage"] == 2
    assert session["items"][0]["question_id"] == question.id
    assert session["items"][0]["reason"]["reasons"] == ["核心巩固"]


async def test_excel_preview_commit_and_duplicate_warning(db_session):
    subject, _, _, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="钱七", grade=9, user_id=None
    )
    wb = Workbook()
    ws = wb.active
    ws.append(["学生姓名", "年级", "学科", "题目ID", "错误原因", "备注", "错误时间"])
    ws.append(["钱七", 9, subject.name, question.id, "计算错误,粗心失误", "导入", "2026-01-01 10:00"])
    buf = io.BytesIO()
    wb.save(buf)
    preview = await service.preview_excel_import(
        db_session, subject_id=subject.id, file_bytes=buf.getvalue(), filename="wrong.xlsx", user_id=None
    )
    assert preview["summary"]["ready"] == 1
    assert (await db_session.execute(select(func.count()).select_from(LearningAttempt))).scalar_one() == 0
    committed = await service.commit_import(
        db_session, subject_id=subject.id, batch_id=preview["batch_id"], user_id=None
    )
    assert committed["created"] == 1
    assert (await db_session.execute(select(func.count()).select_from(LearningAttempt))).scalar_one() == 1
    second = await service.preview_excel_import(
        db_session, subject_id=subject.id, file_bytes=buf.getvalue(), filename="wrong.xlsx", user_id=None
    )
    assert second["summary"]["duplicate_of_batch_id"] == preview["batch_id"]


async def test_import_rejects_unknown_reason_and_bad_student(db_session):
    subject, _, _, question = await _seed(db_session)
    wb = Workbook()
    ws = wb.active
    ws.append(["学生姓名", "年级", "学科", "题目ID", "错误原因", "备注", "错误时间"])
    ws.append(["不存在", 9, subject.name, question.id, "未知原因", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    preview = await service.preview_excel_import(
        db_session, subject_id=subject.id, file_bytes=buf.getvalue(), filename="bad.xlsx", user_id=None
    )
    row = preview["rows"][0]
    assert row["status"] == "error"
    assert any("未找到学生" in item for item in row["errors"])
    assert any("未知错误原因" in item for item in row["errors"])


async def test_report_contains_required_sections(db_session):
    subject, _, _, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="孙八", grade=9, user_id=None
    )
    await service.create_attempt(
        db_session, subject_id=subject.id, student_id=student["id"], question_id=question.id,
        result="partial", error_reasons=["表达不规范"],
    )
    report = await service.student_report(db_session, subject_id=subject.id, student_id=student["id"])
    assert report["student"]["name"] == "孙八"
    assert report["summary"]["attempts"] == 1
    assert report["summary"]["partial"] == 1
    assert report["wrong_questions"]
    assert report["mastery"]["knowledge_points"]
    assert report["type_mastery"]


async def test_natural_language_import_preview(db_session, monkeypatch):
    subject, _, _, question = await _seed(db_session)
    student = await service.create_student(
        db_session, subject_id=subject.id, name="周九", grade=9, user_id=None
    )

    async def fake_resolve(db, is_vision=False):
        return "openai", {"API_KEY": "x", "MODEL_NAME": "m"}

    class FakeProvider:
        async def chat_stream(self, messages, config, tools=None):
            yield '```json\n[{"student_name":"周九","grade":9,"subject":"数学","question_id":%d,"error_reasons":["计算错误"],"note":"nl","answered_at":""}]\n```' % question.id

    monkeypatch.setattr(
        "app.services.importing.provider_config.resolve_active_provider", fake_resolve
    )
    monkeypatch.setattr("app.services.ai_provider.get_ai_provider", lambda name: FakeProvider())
    preview = await service.preview_nl_import(
        db_session, subject_id=subject.id, text="周九第 %d 题计算错误" % question.id, user_id=None
    )
    assert preview["summary"]["ready"] == 1
    assert preview["rows"][0]["student_id"] == student["id"]
    assert (await db_session.execute(select(func.count()).select_from(LearningAttempt))).scalar_one() == 0


async def test_natural_language_import_invalid_json(db_session, monkeypatch):
    subject, _, _, _ = await _seed(db_session)

    async def fake_resolve(db, is_vision=False):
        return "openai", {"API_KEY": "x", "MODEL_NAME": "m"}

    class FakeProvider:
        async def chat_stream(self, messages, config, tools=None):
            yield "not json"

    monkeypatch.setattr(
        "app.services.importing.provider_config.resolve_active_provider", fake_resolve
    )
    monkeypatch.setattr("app.services.ai_provider.get_ai_provider", lambda name: FakeProvider())
    with pytest.raises(service.LearningError):
        await service.preview_nl_import(
            db_session, subject_id=subject.id, text="坏数据", user_id=None
        )


async def test_import_errors_csv(db_session):
    subject, _, _, question = await _seed(db_session)
    wb = Workbook()
    ws = wb.active
    ws.append(["学生姓名", "年级", "学科", "题目ID", "错误原因", "备注", "错误时间"])
    ws.append(["不存在", 9, subject.name, question.id, "计算错误", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    preview = await service.preview_excel_import(
        db_session, subject_id=subject.id, file_bytes=buf.getvalue(), filename="bad.xlsx", user_id=None
    )
    csv_bytes = await service.import_errors_csv(
        db_session, subject_id=subject.id, batch_id=preview["batch_id"]
    )
    text = csv_bytes.decode("utf-8-sig")
    assert "未找到学生" in text
    assert "不存在" in text


async def test_csv_import_preview(db_session):
    subject, _, _, question = await _seed(db_session)
    await service.create_student(
        db_session, subject_id=subject.id, name="吴十", grade=9, user_id=None
    )
    csv_text = "学生姓名,年级,学科,题目ID,错误原因,备注,错误时间\n吴十,9,%s,%d,计算错误,CSV,\n" % (subject.name, question.id)
    preview = await service.preview_excel_import(
        db_session,
        subject_id=subject.id,
        file_bytes=csv_text.encode("utf-8-sig"),
        filename="wrong.csv",
        user_id=None,
    )
    assert preview["summary"]["ready"] == 1
    assert preview["rows"][0]["student_id"] is not None


async def test_natural_language_ai_failure_is_reported(db_session, monkeypatch):
    subject, _, _, _ = await _seed(db_session)

    async def fake_resolve(db, is_vision=False):
        return "openai", {"API_KEY": "x", "MODEL_NAME": "m"}

    class FakeProvider:
        async def chat_stream(self, messages, config, tools=None):
            raise TimeoutError("upstream timeout")
            yield ""

    monkeypatch.setattr(
        "app.services.importing.provider_config.resolve_active_provider", fake_resolve
    )
    monkeypatch.setattr("app.services.ai_provider.get_ai_provider", lambda name: FakeProvider())
    with pytest.raises(service.LearningError) as exc:
        await service.preview_nl_import(db_session, subject_id=subject.id, text="任意文本", user_id=None)
    assert "AI 调用失败" in str(exc.value)


async def test_ambiguous_student_match_is_rejected(db_session):
    subject, _, _, question = await _seed(db_session)
    await service.create_student(db_session, subject_id=subject.id, name="重复", grade=9, user_id=None)
    await service.create_student(db_session, subject_id=subject.id, name="重复", grade=9, user_id=None)
    wb = Workbook()
    ws = wb.active
    ws.append(["学生姓名", "年级", "学科", "题目ID", "错误原因", "备注", "错误时间"])
    ws.append(["重复", 9, subject.name, question.id, "计算错误", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    preview = await service.preview_excel_import(
        db_session, subject_id=subject.id, file_bytes=buf.getvalue(), filename="ambiguous.xlsx", user_id=None
    )
    row = preview["rows"][0]
    assert row["status"] == "error"
    assert any("不唯一" in item for item in row["errors"])


async def test_recommend_four_stage_difficulty_range(db_session):
    subject, kp1, _, question = await _seed(db_session)
    question.difficulty = 2
    question.status = "pending"
    await db_session.commit()
    student = await service.create_student(
        db_session, subject_id=subject.id, name="孙八", grade=9, user_id=None
    )
    result = await service.recommend_questions(
        db_session,
        subject_id=subject.id,
        student_id=student["id"],
        mode="four_stage",
        stage=1,
        limit=3,
        include_unpublished=True,
    )
    assert result["items"], result
    assert result["items"][0]["question_id"] == question.id
