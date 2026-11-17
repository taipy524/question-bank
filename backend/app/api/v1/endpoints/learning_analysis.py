from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app import models
from app.api import deps
from app.core.permissions import Permission
from app.schemas.learning_analysis import (
    AttemptCreate,
    ConfigUpdate,
    NLImportRequest,
    SessionCreate,
    StudentCreate,
    StudentUpdate,
)
from app.services import learning_analysis_service as service

router = APIRouter()
MAX_IMPORT_SIZE = 5 * 1024 * 1024


def _authorize(user: models.User, subject_id: int) -> None:
    deps.require(user, Permission.MANAGE_SUBJECT, subject_id=subject_id)


def _raise(exc: service.LearningError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/students")
async def list_students(
    db: deps.SessionDep,
    subject_id: int,
    search: Optional[str] = None,
    grade: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    return await service.list_students(
        db, subject_id=subject_id, search=search, grade=grade, skip=skip, limit=limit
    )


@router.post("/students")
async def create_student(
    payload: StudentCreate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, payload.subject_id)
    try:
        return await service.create_student(
            db,
            subject_id=payload.subject_id,
            name=payload.name,
            grade=payload.grade,
            user_id=current_user.id,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.patch("/students/{student_id}")
async def update_student(
    student_id: int,
    payload: StudentUpdate,
    db: deps.SessionDep,
    subject_id: int = Query(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.update_student(
            db,
            subject_id=subject_id,
            student_id=student_id,
            name=payload.name,
            grade=payload.grade,
            user_id=current_user.id,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: int,
    db: deps.SessionDep,
    subject_id: int = Query(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.delete_student(
            db, subject_id=subject_id, student_id=student_id, user_id=current_user.id
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/students/{student_id}/report")
async def student_report(
    student_id: int,
    db: deps.SessionDep,
    subject_id: int = Query(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.student_report(db, subject_id=subject_id, student_id=student_id)
    except service.LearningError as exc:
        _raise(exc)


@router.post("/attempts")
async def create_attempt(
    payload: AttemptCreate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, payload.subject_id)
    try:
        return await service.create_attempt(
            db,
            subject_id=payload.subject_id,
            student_id=payload.student_id,
            question_id=payload.question_id,
            result=payload.result,
            error_reasons=payload.error_reasons,
            note=payload.note,
            answered_at=payload.answered_at,
            session_id=payload.session_id,
            user_id=current_user.id,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/attempts")
async def list_attempts(
    db: deps.SessionDep,
    subject_id: int,
    student_id: Optional[int] = None,
    question_id: Optional[int] = None,
    result: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.list_attempts(
            db,
            subject_id=subject_id,
            student_id=student_id,
            question_id=question_id,
            result=result,
            limit=limit,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/wrong-questions")
async def wrong_questions(
    db: deps.SessionDep,
    subject_id: int,
    student_id: Optional[int] = None,
    limit: int = Query(200, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.list_wrong_questions(
            db, subject_id=subject_id, student_id=student_id, limit=limit
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/mastery")
async def mastery(
    db: deps.SessionDep,
    subject_id: int,
    student_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.compute_mastery(db, subject_id=subject_id, student_id=student_id)
    except service.LearningError as exc:
        _raise(exc)


@router.get("/mastery/types")
async def type_mastery(
    db: deps.SessionDep,
    subject_id: int,
    student_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.compute_type_mastery(db, subject_id=subject_id, student_id=student_id)
    except service.LearningError as exc:
        _raise(exc)


@router.get("/recommendations")
async def recommendations(
    db: deps.SessionDep,
    subject_id: int,
    student_id: int,
    mode: str = "recommendation",
    stage: Optional[int] = None,
    limit: int = Query(10, ge=1, le=100),
    knowledge_point_ids: list[int] = Query(default=[]),
    question_ids: list[int] = Query(default=[]),
    include_unpublished: bool = False,
    exclude_practiced: bool = True,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.recommend_questions(
            db,
            subject_id=subject_id,
            student_id=student_id,
            knowledge_point_ids=knowledge_point_ids or None,
            question_ids=question_ids or None,
            mode=mode,
            stage=stage,
            limit=limit,
            include_unpublished=include_unpublished,
            exclude_practiced=exclude_practiced,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.post("/sessions")
async def create_session(
    payload: SessionCreate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, payload.subject_id)
    try:
        return await service.create_session(
            db,
            subject_id=payload.subject_id,
            student_id=payload.student_id,
            question_ids=payload.question_ids,
            mode=payload.mode,
            stage=payload.stage,
            title=payload.title,
            reasons=payload.reasons,
            user_id=current_user.id,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/sessions")
async def list_sessions(
    db: deps.SessionDep,
    subject_id: int,
    student_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.list_sessions(
            db, subject_id=subject_id, student_id=student_id, limit=limit
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: deps.SessionDep,
    subject_id: int = Query(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.get_session(db, subject_id=subject_id, session_id=session_id)
    except service.LearningError as exc:
        _raise(exc)


@router.get("/reviews")
async def reviews(
    db: deps.SessionDep,
    subject_id: int,
    student_id: Optional[int] = None,
    due_only: bool = False,
    limit: int = Query(200, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.list_reviews(
            db, subject_id=subject_id, student_id=student_id, due_only=due_only, limit=limit
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/config")
async def get_config(
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="superuser only")
    return await service.get_config(db)


@router.put("/config")
async def update_config(
    payload: ConfigUpdate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    return await service.update_config(db, payload.model_dump(exclude_unset=True))


@router.get("/imports/template")
async def import_template(
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return Response(
        content=service.build_import_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="learning_wrong_import.xlsx"'},
    )


@router.post("/imports/excel")
async def import_excel(
    db: deps.SessionDep,
    subject_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    content = await file.read()
    if len(content) > MAX_IMPORT_SIZE:
        raise HTTPException(status_code=400, detail="文件过大（最多 5MB）")
    try:
        return await service.preview_excel_import(
            db,
            subject_id=subject_id,
            file_bytes=content,
            filename=file.filename or "upload.xlsx",
            user_id=current_user.id,
        )
    except service.LearningError as exc:
        _raise(exc)


@router.post("/imports/nl")
async def import_nl(
    payload: NLImportRequest,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, payload.subject_id)
    try:
        return await service.preview_nl_import(
            db, subject_id=payload.subject_id, text=payload.text, user_id=current_user.id
        )
    except service.LearningError as exc:
        _raise(exc)


@router.post("/imports/{batch_id}/commit")
async def commit_import(
    batch_id: int,
    db: deps.SessionDep,
    subject_id: int = Query(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        return await service.commit_import(
            db, subject_id=subject_id, batch_id=batch_id, user_id=current_user.id
        )
    except service.LearningError as exc:
        _raise(exc)


@router.get("/imports/{batch_id}/errors.csv")
async def import_errors(
    batch_id: int,
    db: deps.SessionDep,
    subject_id: int = Query(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    try:
        content = await service.import_errors_csv(
            db, subject_id=subject_id, batch_id=batch_id
        )
    except service.LearningError as exc:
        _raise(exc)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import_errors_{batch_id}.csv"'},
    )


@router.get("/imports")
async def list_imports(
    db: deps.SessionDep,
    subject_id: int,
    limit: int = Query(50, ge=1, le=200),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    _authorize(current_user, subject_id)
    return await service.list_import_batches(db, subject_id=subject_id, limit=limit)
