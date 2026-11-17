from typing import Any, Optional

from pydantic import BaseModel, Field


class StudentCreate(BaseModel):
    subject_id: int
    name: str
    grade: int


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    grade: Optional[int] = None


class AttemptCreate(BaseModel):
    subject_id: int
    student_id: int
    question_id: int
    result: str = Field(description="correct|wrong|partial")
    error_reasons: list[str] = []
    note: Optional[str] = None
    answered_at: Optional[str] = None
    session_id: Optional[int] = None


class SessionCreate(BaseModel):
    subject_id: int
    student_id: int
    question_ids: list[int]
    mode: str = "recommendation"
    stage: Optional[int] = None
    title: Optional[str] = None
    reasons: Optional[dict[str, list[str]]] = None


class ConfigUpdate(BaseModel):
    partial_weight: Optional[float] = None
    review_intervals: Optional[list[int]] = None
    mastery_min_samples: Optional[int] = None
    mastery_thresholds: Optional[dict[str, float]] = None
    default_recommendation_status: Optional[str] = None


class NLImportRequest(BaseModel):
    subject_id: int
    text: str
