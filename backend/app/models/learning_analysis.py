"""Learning analysis tables (admin/manager only, no student accounts)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class LearningStudent(Base):
    __tablename__ = "learning_students"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False, index=True)
    grade = Column(SmallInteger, nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    subject = relationship("Subject")
    attempts = relationship(
        "LearningAttempt", back_populates="student", cascade="all, delete-orphan"
    )
    wrong_stats = relationship(
        "LearningWrongStat", back_populates="student", cascade="all, delete-orphan"
    )
    sessions = relationship(
        "LearningSession", back_populates="student", cascade="all, delete-orphan"
    )
    reviews = relationship(
        "LearningReviewSchedule", back_populates="student", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_learning_students_subject_name_grade", "subject_id", "name", "grade"),
    )


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = Column(
        Integer,
        ForeignKey("learning_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode = Column(String(32), nullable=False, default="recommendation")
    stage = Column(SmallInteger, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    title = Column(String(255), nullable=True)
    config = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    student = relationship("LearningStudent", back_populates="sessions")
    items = relationship(
        "LearningSessionItem",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="LearningSessionItem.sequence",
    )

    __table_args__ = (
        Index("ix_learning_sessions_subject_student", "subject_id", "student_id"),
    )


class LearningSessionItem(Base):
    __tablename__ = "learning_session_items"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        Integer, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence = Column(Integer, nullable=False)
    stage = Column(SmallInteger, nullable=True)
    reason = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    session = relationship("LearningSession", back_populates="items")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_learning_session_question"),
        Index("ix_learning_items_session_seq", "session_id", "sequence"),
    )


class LearningAttempt(Base):
    __tablename__ = "learning_attempts"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = Column(
        Integer,
        ForeignKey("learning_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        Integer, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_id = Column(
        Integer,
        ForeignKey("learning_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    result = Column(String(16), nullable=False)
    error_reasons = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)
    answered_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source = Column(String(32), nullable=False, default="manual")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    student = relationship("LearningStudent", back_populates="attempts")
    question = relationship("Question")

    __table_args__ = (
        CheckConstraint(
            "result IN ('correct','wrong','partial')",
            name="ck_learning_attempt_result",
        ),
        Index("ix_learning_attempts_student_time", "student_id", "answered_at"),
        Index("ix_learning_attempts_student_question", "student_id", "question_id"),
        Index("ix_learning_attempts_subject", "subject_id"),
    )


class LearningWrongStat(Base):
    __tablename__ = "learning_wrong_stats"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = Column(
        Integer,
        ForeignKey("learning_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        Integer, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    wrong_count = Column(Integer, nullable=False, default=0)
    partial_count = Column(Integer, nullable=False, default=0)
    last_wrong_at = Column(DateTime, nullable=True, index=True)
    error_reasons = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    student = relationship("LearningStudent", back_populates="wrong_stats")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("student_id", "question_id", name="uq_learning_wrong_student_question"),
        Index("ix_learning_wrong_subject_student", "subject_id", "student_id"),
    )


class LearningReviewSchedule(Base):
    __tablename__ = "learning_review_schedules"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = Column(
        Integer,
        ForeignKey("learning_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        Integer, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    due_at = Column(DateTime, nullable=False, index=True)
    interval_days = Column(Integer, nullable=False, default=1)
    ease_factor = Column(Float, nullable=False, default=2.5)
    repetitions = Column(Integer, nullable=False, default=0)
    lapses = Column(Integer, nullable=False, default=0)
    last_result = Column(String(16), nullable=True)
    status = Column(String(16), nullable=False, default="scheduled")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    student = relationship("LearningStudent", back_populates="reviews")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("student_id", "question_id", name="uq_learning_review_student_question"),
        Index("ix_learning_review_due", "subject_id", "due_at", "status"),
    )


class LearningImportBatch(Base):
    __tablename__ = "learning_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(16), nullable=False)  # excel | nl
    status = Column(String(16), nullable=False, default="preview")
    content_hash = Column(String(64), nullable=True, index=True)
    payload = Column(JSON, nullable=True)
    summary = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    committed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_learning_imports_subject_status", "subject_id", "status"),
    )
