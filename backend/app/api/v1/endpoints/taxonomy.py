from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app import models
from app.api import deps
from app.schemas.taxonomy import (
    BatchCreate,
    MappingTargetsPayload,
    NewTopicApproval,
    QuestionLinkReviewAction,
    ReviewAction,
    SourceCreate,
)
from app.services import taxonomy_service as service
from app.services import taxonomy_source_import as source_import

router = APIRouter()


def _raise(exc: service.TaxonomyError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/sources")
async def list_sources(
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_sources(db)


@router.post("/sources")
async def create_source(
    payload: SourceCreate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        source = await service.create_source(
            db,
            slug=payload.slug,
            repo_url=payload.repo_url,
            commit_sha=payload.commit_sha,
            license_status=payload.license_status,
            license_note=payload.license_note,
            data_version=payload.data_version,
            content_hash=payload.content_hash,
        )
    except Exception as exc:  # unique violation is surfaced as 400
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": source.id,
        "slug": source.slug,
        "commit_sha": source.commit_sha,
        "license_status": source.license_status,
        "status": source.status,
    }


@router.get("/external-topics")
async def list_external_topics(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    grade: Optional[int] = None,
    domain: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await source_import.list_external_topics(
        db,
        source_id=source_id,
        grade=grade,
        domain=domain,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.get("/external-relations")
async def list_external_relations(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    relation_kind: Optional[str] = None,
    strength: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(200, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await source_import.list_external_relations(
        db,
        source_id=source_id,
        relation_kind=relation_kind,
        strength=strength,
        skip=skip,
        limit=limit,
    )


@router.get("/external-standard-links")
async def list_external_standard_links(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    external_topic_id: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(500, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await source_import.list_external_topic_standards(
        db,
        source_id=source_id,
        external_topic_id=external_topic_id,
        skip=skip,
        limit=limit,
    )


@router.get("/mappings")
async def list_mappings(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    review_status: Optional[str] = None,
    match_type: Optional[str] = None,
    high_risk: Optional[bool] = None,
    include_history: bool = False,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_mappings(
        db,
        source_id=source_id,
        review_status=review_status,
        match_type=match_type,
        high_risk=high_risk,
        include_history=include_history,
        skip=skip,
        limit=limit,
    )


@router.get("/mappings/{mapping_id}")
async def get_mapping(
    mapping_id: int,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    try:
        row = await service.get_mapping(db, mapping_id)
    except service.TaxonomyError as exc:
        _raise(exc)
    return service._as_dict(row)


@router.get("/mappings/{mapping_id}/history")
async def mapping_history(
    mapping_id: int,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    try:
        row = await service.get_mapping(db, mapping_id, current_only=False)
    except service.TaxonomyError as exc:
        _raise(exc)
    return await service.mapping_history(
        db,
        source_id=row.source_id,
        external_topic_id=row.external_topic_id,
        internal_knowledge_point_id=row.internal_knowledge_point_id,
    )


@router.post("/mappings/{mapping_id}/review")
async def review_mapping(
    mapping_id: int,
    payload: ReviewAction,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        if payload.action == "reassign":
            if payload.new_knowledge_point_id is None:
                raise service.TaxonomyError(
                    "reassign requires new_knowledge_point_id"
                )
            return await service.reassign_mapping(
                db,
                mapping_id=mapping_id,
                internal_knowledge_point_id=payload.new_knowledge_point_id,
                reviewer_id=current_user.id,
                comment=payload.comment,
            )
        return await service.review_mapping(
            db,
            mapping_id=mapping_id,
            action=payload.action,
            reviewer_id=current_user.id,
            comment=payload.comment,
            acknowledge_high_risk=payload.acknowledge_high_risk,
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.get("/new-topics")
async def list_new_topics(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_new_topics(db, source_id=source_id, skip=skip, limit=limit)


@router.post("/new-topics/{mapping_id}/approve")
async def approve_new_topic(
    mapping_id: int,
    payload: NewTopicApproval,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.approve_new_topic(
            db,
            mapping_id=mapping_id,
            reviewer_id=current_user.id,
            subject_id=payload.subject_id,
            parent_id=payload.parent_id,
            name=payload.name,
            comment=payload.comment,
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.post("/new-topics/{mapping_id}/reject")
async def reject_new_topic(
    mapping_id: int,
    payload: ReviewAction,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.reject_new_topic(
            db,
            mapping_id=mapping_id,
            reviewer_id=current_user.id,
            comment=payload.comment,
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.get("/prerequisites")
async def list_prerequisites(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    current_only: bool = True,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_prerequisites(db, source_id=source_id, current_only=current_only)


@router.get("/prerequisites/conflicts")
async def prerequisite_conflicts(
    db: deps.SessionDep,
    source_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.prerequisite_conflicts(db, source_id=source_id)


@router.post("/prerequisites/{prerequisite_id}/review")
async def review_prerequisite(
    prerequisite_id: int,
    payload: ReviewAction,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.review_prerequisite(
            db,
            prerequisite_id=prerequisite_id,
            action=payload.action,
            reviewer_id=current_user.id,
            comment=payload.comment,
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.get("/standards")
async def list_standards(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(200, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_standards(db, source_id=source_id, skip=skip, limit=limit)


@router.get("/standard-links")
async def list_standard_links(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    review_status: Optional[str] = None,
    current_only: bool = True,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_topic_standards(
        db, source_id=source_id, review_status=review_status, current_only=current_only
    )


@router.post("/standard-links/{link_id}/review")
async def review_standard_link(
    link_id: int,
    payload: ReviewAction,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.review_topic_standard(
            db,
            link_id=link_id,
            action=payload.action,
            reviewer_id=current_user.id,
            comment=payload.comment,
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.get("/batches")
async def list_batches(
    db: deps.SessionDep,
    source_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_batches(db, source_id=source_id, skip=skip, limit=limit)


@router.post("/batches/preview")
async def preview_batch(
    payload: BatchCreate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    try:
        return await service.preview_batch(db, source_id=payload.source_id)
    except service.TaxonomyError as exc:
        _raise(exc)


@router.post("/batches")
async def create_batch(
    payload: BatchCreate,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        batch = await service.create_batch(
            db,
            source_id=payload.source_id,
            mode=payload.mode,
            user_id=current_user.id,
            notes=payload.notes,
        )
    except service.TaxonomyError as exc:
        _raise(exc)
    return {
        "id": batch.id,
        "source_id": batch.source_id,
        "mode": batch.mode,
        "status": batch.status,
        "summary": batch.summary,
        "conflicts": batch.conflicts,
    }


@router.post("/batches/{batch_id}/execute")
async def execute_batch(
    batch_id: int,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.execute_batch(db, batch_id=batch_id, user_id=current_user.id)
    except service.TaxonomyError as exc:
        _raise(exc)


@router.post("/batches/{batch_id}/rollback")
async def rollback_batch(
    batch_id: int,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.rollback_batch(db, batch_id=batch_id, user_id=current_user.id)
    except service.TaxonomyError as exc:
        _raise(exc)

@router.post("/mappings/{mapping_id}/targets")
async def set_mapping_targets(
    mapping_id: int,
    payload: MappingTargetsPayload,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.set_mapping_targets(
            db,
            mapping_id=mapping_id,
            knowledge_point_ids=payload.knowledge_point_ids,
            reviewer_id=current_user.id,
            comment=payload.comment,
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.post("/mappings/{mapping_id}/targets/confirm")
async def confirm_mapping_targets(
    mapping_id: int,
    db: deps.SessionDep,
    comment: str = "",
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.confirm_mapping_targets(
            db, mapping_id=mapping_id, reviewer_id=current_user.id, comment=comment
        )
    except service.TaxonomyError as exc:
        _raise(exc)


@router.get("/question-links")
async def list_question_links(
    db: deps.SessionDep,
    review_status: Optional[str] = None,
    result: Optional[str] = None,
    question_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await service.list_question_links(
        db,
        review_status=review_status,
        result=result,
        question_id=question_id,
        skip=skip,
        limit=limit,
    )


@router.get("/question-links/{link_id}")
async def get_question_link(
    link_id: int,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    try:
        return await service.get_question_link(db, link_id)
    except service.TaxonomyError as exc:
        _raise(exc)


@router.post("/question-links/{link_id}/review")
async def review_question_link(
    link_id: int,
    payload: QuestionLinkReviewAction,
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await service.review_question_link(
            db,
            link_id=link_id,
            action=payload.action,
            reviewer_id=current_user.id,
            comment=payload.comment,
            new_knowledge_point_id=payload.new_knowledge_point_id,
        )
    except service.TaxonomyError as exc:
        _raise(exc)
