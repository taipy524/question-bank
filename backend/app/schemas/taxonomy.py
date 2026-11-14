from typing import Optional

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    slug: str
    repo_url: str
    commit_sha: str
    license_status: str = "unconfirmed"
    license_note: Optional[str] = None
    data_version: Optional[str] = None
    content_hash: Optional[str] = None


class ReviewAction(BaseModel):
    action: str = Field(
        description="confirm|reject|defer|split|merge|undo|reopen|reassign"
    )
    comment: str = ""
    acknowledge_high_risk: bool = False
    new_knowledge_point_id: Optional[int] = None


class MappingTargetsPayload(BaseModel):
    knowledge_point_ids: list[int] = Field(min_length=2)
    comment: str = ""


class QuestionLinkReviewAction(BaseModel):
    action: str = Field(description="approve|reject|defer|reopen")
    comment: str = ""
    new_knowledge_point_id: Optional[int] = None


class NewTopicApproval(BaseModel):
    subject_id: int
    parent_id: Optional[int] = None
    name: Optional[str] = None
    comment: str = ""


class BatchCreate(BaseModel):
    source_id: int
    mode: str = "dry_run"
    notes: Optional[str] = None
