from typing import Any, List, Optional
import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from app import crud, schemas, models
from app.api import deps
from app.core.permissions import Permission
from app.core.vector_store import VectorStore
from app.services import kp_import_service
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from app.models.knowledge_point import KnowledgePoint
from app.models.taxonomy import (
    KnowledgePointTaxonomy,
    TaxonomyPrerequisite,
    TaxonomyStandard,
    TaxonomyTopicStandard,
)


def _kp_payload(kp: KnowledgePoint) -> dict:
    meta = kp.taxonomy_meta
    return {
        "id": kp.id,
        "name": kp.name,
        "slug": kp.slug,
        "subject_id": kp.subject_id,
        "parent_id": kp.parent_id,
        "created_at": kp.created_at,
        "updated_at": kp.updated_at,
        "grade": meta.grade if meta else None,
        "semester": meta.semester if meta else None,
        "chapter": meta.chapter if meta else None,
        "domain": meta.domain if meta else None,
        # Formal = imported/manually-created with taxonomy metadata. Legacy
        # knowledge points (the pre-import 62) have no metadata row.
        "is_formal": bool(meta is not None and not meta.is_legacy),
    }


async def _count_formal_kps(db, subject_id: Optional[int] = None) -> int:
    stmt = (
        select(func.count())
        .select_from(KnowledgePoint)
        .join(
            KnowledgePointTaxonomy,
            KnowledgePointTaxonomy.knowledge_point_id == KnowledgePoint.id,
        )
        .where(
            KnowledgePointTaxonomy.is_legacy.is_(False),
            KnowledgePointTaxonomy.is_active.is_(True),
        )
    )
    if subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == subject_id)
    return (await db.execute(stmt)).scalar_one()


async def _load_kp(db, kp_id: int) -> KnowledgePoint | None:
    return (
        await db.execute(
            select(KnowledgePoint)
            .options(selectinload(KnowledgePoint.taxonomy_meta))
            .where(KnowledgePoint.id == kp_id)
        )
    ).scalar_one_or_none()

router = APIRouter()

MAX_IMPORT_SIZE = 5 * 1024 * 1024  # 5 MB


@router.get("", response_model=List[schemas.KnowledgePoint])
async def read_knowledge_points(
    db: deps.SessionDep,
    skip: int = 0,
    limit: int = 100,
    subject_id: Optional[int] = None,
    grade: Optional[int] = None,
    semester: Optional[str] = None,
    chapter: Optional[str] = None,
    domain: Optional[str] = None,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve knowledge points.

    Supports grade / semester / chapter / domain filtering.  Set limit to -1
    to retrieve every matching knowledge point.
    """
    if subject_id:
        deps.require(current_user, Permission.VIEW_QUESTION, subject_id=subject_id)

    stmt = select(KnowledgePoint).options(selectinload(KnowledgePoint.taxonomy_meta))
    if subject_id:
        stmt = stmt.where(KnowledgePoint.subject_id == subject_id)
    if any(value is not None for value in (grade, semester, chapter, domain)):
        stmt = stmt.join(
            KnowledgePointTaxonomy,
            KnowledgePointTaxonomy.knowledge_point_id == KnowledgePoint.id,
        )
        if grade is not None:
            stmt = stmt.where(KnowledgePointTaxonomy.grade == grade)
        if semester is not None:
            stmt = stmt.where(KnowledgePointTaxonomy.semester == semester)
        if chapter is not None:
            stmt = stmt.where(KnowledgePointTaxonomy.chapter == chapter)
        if domain is not None:
            stmt = stmt.where(KnowledgePointTaxonomy.domain == domain)

    stmt = stmt.order_by(KnowledgePoint.id)
    if limit != -1:
        stmt = stmt.offset(skip).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [_kp_payload(kp) for kp in rows]


@router.get("/{id}/prerequisites")
async def read_knowledge_point_prerequisites(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """Prerequisites (what must be learned before this knowledge point)."""
    kp = await _load_kp(db, id)
    if not kp:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=kp.subject_id)

    rows = (
        await db.execute(
            select(TaxonomyPrerequisite, KnowledgePoint, KnowledgePointTaxonomy)
            .join(
                KnowledgePoint,
                KnowledgePoint.id == TaxonomyPrerequisite.prerequisite_knowledge_point_id,
            )
            .outerjoin(
                KnowledgePointTaxonomy,
                KnowledgePointTaxonomy.knowledge_point_id == KnowledgePoint.id,
            )
            .where(
                TaxonomyPrerequisite.knowledge_point_id == id,
                TaxonomyPrerequisite.is_current.is_(True),
            )
            .order_by(KnowledgePoint.id)
        )
    ).all()
    return [
        {
            "id": link.id,
            "prerequisite_id": prereq.id,
            "name": prereq.name,
            "slug": prereq.slug,
            "strength": link.strength,
            "grade": meta.grade if meta else None,
            "semester": meta.semester if meta else None,
            "chapter": meta.chapter if meta else None,
            "domain": meta.domain if meta else None,
        }
        for link, prereq, meta in rows
    ]


@router.get("/{id}/standards")
async def read_knowledge_point_standards(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """Curriculum standards mapped to this knowledge point."""
    kp = await _load_kp(db, id)
    if not kp:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=kp.subject_id)

    rows = (
        await db.execute(
            select(TaxonomyTopicStandard, TaxonomyStandard)
            .join(
                TaxonomyStandard,
                TaxonomyStandard.id == TaxonomyTopicStandard.standard_id,
            )
            .where(
                TaxonomyTopicStandard.knowledge_point_id == id,
                TaxonomyTopicStandard.is_current.is_(True),
            )
            .order_by(TaxonomyStandard.standard_id)
        )
    ).all()
    return [
        {
            "id": link.id,
            "standard_id": standard.standard_id,
            "content": standard.content,
            "domain": standard.domain,
            "section": standard.section,
            "confidence": link.confidence,
        }
        for link, standard in rows
    ]


# --- Vector sync (deferred indexing) ---

@router.get("/embedding-status")
async def get_embedding_status(
    db: deps.SessionDep,
    subject_id: Optional[int] = None,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """Import-page readiness: whether embedding is configured and the subject's KPs are vectorized."""
    embedding_configured = VectorStore.is_available()
    chroma_reachable = VectorStore.is_reachable()

    kp_total = await _count_formal_kps(db, subject_id)

    # Empty subject has nothing to vectorize; treat as "vectorized".
    kp_vectorized = True
    if embedding_configured and chroma_reachable and kp_total > 0:
        vec_count = VectorStore.count_by_subject(subject_id) if subject_id is not None else VectorStore.count()
        kp_vectorized = vec_count >= kp_total

    return {
        "embedding_configured": embedding_configured,
        "chroma_reachable": chroma_reachable,
        "kp_total": kp_total,
        "kp_vectorized": kp_vectorized,
    }


@router.get("/vector-status", response_model=schemas.VectorStatus)
async def get_vector_status(
    db: deps.SessionDep,
    subject_id: Optional[int] = None,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Report whether the knowledge point vectors are in sync with the database.
    Used by the UI to prompt for a manual reindex when needed.
    """
    embedding_configured = VectorStore.is_available()

    db_count = await _count_formal_kps(db, subject_id)

    if not embedding_configured:
        vector_count = 0
    elif subject_id is not None:
        vector_count = VectorStore.count_by_subject(subject_id)
    else:
        vector_count = VectorStore.count()

    if not embedding_configured:
        needs_reindex = False
        reason = "未配置向量模型，语义检索不可用"
    elif db_count != vector_count:
        needs_reindex = True
        diff = abs(db_count - vector_count)
        reason = f"{diff} 个知识点尚未同步向量索引"
    else:
        needs_reindex = False
        reason = "向量索引已是最新"

    return schemas.VectorStatus(
        embedding_configured=embedding_configured,
        db_count=db_count,
        vector_count=vector_count,
        needs_reindex=needs_reindex,
        reason=reason,
    )


@router.post("/reindex-vectors", response_model=schemas.ReindexResult)
async def reindex_vectors(
    *,
    db: deps.SessionDep,
    subject_id: Optional[int] = None,
    full: bool = False,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Rebuild the knowledge point vector index from the database.
    """
    if not VectorStore.is_available():
        raise HTTPException(
            status_code=400,
            detail="请先在 AI 供应商与模型中配置并激活 Embedding 模型",
        )
    import time
    started = time.perf_counter()
    try:
        count = await crud.knowledge_point.reindex_vectors(
            db, subject_id=subject_id, full=full
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"向量重建失败：{e}")
    return schemas.ReindexResult(
        status="success",
        reindexed=count,
        duration=round(time.perf_counter() - started, 2),
    )


# --- Batch import ---

@router.get("/import-template")
async def download_import_template(
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Download the .xlsx knowledge point import template."""
    content = kp_import_service.generate_template()
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="knowledge_points_template.xlsx"'
        },
    )


@router.get("/import-preflight", response_model=schemas.KPImportPreflight)
async def import_preflight(
    *,
    db: deps.SessionDep,
    subject_id: int,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Impact assessment for the rebuild mode (existing count, affected questions)."""
    result = await kp_import_service.preflight(db, subject_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return result


@router.post("/import", response_model=schemas.KPImportResult)
async def import_knowledge_points(
    *,
    db: deps.SessionDep,
    file: UploadFile = File(...),
    mode: str = Form("incremental"),
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """Batch import knowledge points from an .xlsx file."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式的文件")
    if mode not in ("incremental", "rebuild"):
        raise HTTPException(status_code=400, detail="无效的导入模式")

    content = await file.read()
    if len(content) > MAX_IMPORT_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，请确保文件小于 5MB")

    result = await kp_import_service.import_excel(
        db, file_bytes=content, mode=mode, user_id=current_user.id
    )
    return result


@router.post("", response_model=schemas.KnowledgePoint)
async def create_knowledge_point(
    *,
    db: deps.SessionDep,
    knowledge_point_in: schemas.KnowledgePointCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    deps.require(current_user, Permission.MANAGE_SUBJECT, subject_id=knowledge_point_in.subject_id)
    try:
        knowledge_point = await crud.knowledge_point.create(db=db, obj_in=knowledge_point_in, user_id=current_user.id)
        knowledge_point = await _load_kp(db, knowledge_point.id)
        return _kp_payload(knowledge_point)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Knowledge point with this slug already exists in this subject")

@router.put("/{id}", response_model=schemas.KnowledgePoint)
async def update_knowledge_point(
    *,
    db: deps.SessionDep,
    id: int,
    knowledge_point_in: schemas.KnowledgePointUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    knowledge_point = await crud.knowledge_point.get(db=db, id=id)
    if not knowledge_point:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    deps.require(current_user, Permission.MANAGE_SUBJECT, subject_id=knowledge_point.subject_id)
    knowledge_point = await crud.knowledge_point.update(db=db, db_obj=knowledge_point, obj_in=knowledge_point_in, user_id=current_user.id)
    knowledge_point = await _load_kp(db, knowledge_point.id)
    return _kp_payload(knowledge_point)

@router.get("/{id}", response_model=schemas.KnowledgePoint)
async def read_knowledge_point(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get knowledge point by ID.
    """
    knowledge_point = await _load_kp(db, id)
    if not knowledge_point:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=knowledge_point.subject_id)
    return _kp_payload(knowledge_point)

@router.delete("/{id}", response_model=schemas.KnowledgePoint)
async def delete_knowledge_point(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a knowledge point.
    """
    knowledge_point = await crud.knowledge_point.get(db=db, id=id)
    if not knowledge_point:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    deps.require(current_user, Permission.MANAGE_SUBJECT, subject_id=knowledge_point.subject_id)
    knowledge_point = await crud.knowledge_point.remove(db=db, id=id, user_id=current_user.id)
    return knowledge_point
