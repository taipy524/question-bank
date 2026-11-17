import io

from openpyxl import Workbook

from app.core.security import create_access_token
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question, QuestionType
from app.models.subject import Subject
from app.models.subject_member import SubjectMember
from app.models.user import User

API = "/api/v1/learning-analysis"


async def _user(db, username, superuser=False):
    user = User(
        username=username, full_name=username, hashed_password="x",
        is_active=True, is_superuser=superuser,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def _ctx(db):
    admin = await _user(db, "la-admin", True)
    manager = await _user(db, "la-manager")
    outsider = await _user(db, "la-outsider")
    subject = Subject(name="数学", slug="math-la-api")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    db.add(SubjectMember(user_id=manager.id, subject_id=subject.id, role="manager"))
    await db.commit()
    kp = KnowledgePoint(name="函数", slug="kp-la-api", subject_id=subject.id)
    db.add(kp)
    await db.commit()
    await db.refresh(kp)
    question = Question(
        content='{"type":"doc","content":[]}',
        q_type=QuestionType.SINGLE_CHOICE,
        status="published",
        difficulty=2,
        subject_id=subject.id,
    )
    question.knowledge_points.append(kp)
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return admin, manager, outsider, subject, question


async def test_student_crud_permissions_and_report(client, db_session):
    admin, manager, outsider, subject, question = await _ctx(db_session)
    denied = await client.get(
        f"{API}/students", params={"subject_id": subject.id}, headers=_auth(outsider)
    )
    assert denied.status_code == 403
    created = await client.post(
        f"{API}/students",
        json={"subject_id": subject.id, "name": "张三", "grade": 9},
        headers=_auth(manager),
    )
    assert created.status_code == 200, created.text
    student_id = created.json()["id"]
    attempt = await client.post(
        f"{API}/attempts",
        json={
            "subject_id": subject.id,
            "student_id": student_id,
            "question_id": question.id,
            "result": "wrong",
            "error_reasons": ["计算错误"],
        },
        headers=_auth(manager),
    )
    assert attempt.status_code == 200, attempt.text
    wrong = await client.get(
        f"{API}/wrong-questions",
        params={"subject_id": subject.id, "student_id": student_id},
        headers=_auth(manager),
    )
    assert wrong.status_code == 200
    assert wrong.json()[0]["wrong_count"] == 1
    mastery = await client.get(
        f"{API}/mastery",
        params={"subject_id": subject.id, "student_id": student_id},
        headers=_auth(manager),
    )
    assert mastery.status_code == 200
    report = await client.get(
        f"{API}/students/{student_id}/report",
        params={"subject_id": subject.id},
        headers=_auth(manager),
    )
    assert report.status_code == 200
    assert report.json()["summary"]["wrong"] == 1
    deleted = await client.delete(
        f"{API}/students/{student_id}",
        params={"subject_id": subject.id},
        headers=_auth(manager),
    )
    assert deleted.status_code == 200


async def test_recommendation_no_published_reason(client, db_session):
    admin, manager, outsider, subject, question = await _ctx(db_session)
    question.status = "pending"
    await db_session.commit()
    student = await client.post(
        f"{API}/students",
        json={"subject_id": subject.id, "name": "李四", "grade": 9},
        headers=_auth(manager),
    )
    sid = student.json()["id"]
    empty = await client.get(
        f"{API}/recommendations",
        params={"subject_id": subject.id, "student_id": sid},
        headers=_auth(manager),
    )
    assert empty.status_code == 200
    assert empty.json()["reason"] == "no_published_questions"
    pending = await client.get(
        f"{API}/recommendations",
        params={"subject_id": subject.id, "student_id": sid, "include_unpublished": True},
        headers=_auth(manager),
    )
    assert pending.json()["items"][0]["question_id"] == question.id


async def test_import_excel_preview_and_commit(client, db_session):
    admin, manager, outsider, subject, question = await _ctx(db_session)
    student = await client.post(
        f"{API}/students",
        json={"subject_id": subject.id, "name": "王五", "grade": 9},
        headers=_auth(manager),
    )
    wb = Workbook()
    ws = wb.active
    ws.append(["学生姓名", "年级", "学科", "题目ID", "错误原因", "备注", "错误时间"])
    ws.append(["王五", 9, subject.name, question.id, "计算错误,粗心失误", "导入", ""])
    buf = io.BytesIO()
    wb.save(buf)
    preview = await client.post(
        f"{API}/imports/excel",
        data={"subject_id": str(subject.id)},
        files={"file": ("wrong.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=_auth(manager),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["summary"]["ready"] == 1
    commits = await client.post(
        f"{API}/imports/{body['batch_id']}/commit",
        params={"subject_id": subject.id},
        headers=_auth(manager),
    )
    assert commits.status_code == 200, commits.text
    assert commits.json()["created"] == 1
    attempts = await client.get(
        f"{API}/attempts",
        params={"subject_id": subject.id, "student_id": student.json()["id"]},
        headers=_auth(manager),
    )
    assert len(attempts.json()) == 1


async def test_config_superuser_only(client, db_session):
    admin, manager, outsider, subject, question = await _ctx(db_session)
    denied = await client.get(f"{API}/config", headers=_auth(manager))
    assert denied.status_code == 403
    allowed = await client.get(f"{API}/config", headers=_auth(admin))
    assert allowed.status_code == 200
    assert "partial_weight" in allowed.json()
    updated = await client.put(
        f"{API}/config", json={"partial_weight": 0.4}, headers=_auth(admin)
    )
    assert updated.status_code == 200
    assert updated.json()["partial_weight"] == 0.4
