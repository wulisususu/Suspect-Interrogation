from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, utc_now


class CaseManagement(TimestampMixin, Base):
    __tablename__ = "case_management"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    interruption_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interruption_detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    interrupted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_question_id: Mapped[str | None] = mapped_column(ForeignKey("case_questions.id", ondelete="SET NULL"), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class RecordTimelineEvidence(Base):
    __tablename__ = "record_timeline_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AnswerCorrection(Base):
    __tablename__ = "answer_corrections"
    __table_args__ = (UniqueConstraint("question_id", "answer_hash", "start_index", "original", "suggestion", name="uq_answer_correction_revision"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("case_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    start_index: Mapped[int] = mapped_column(Integer, nullable=False)
    original: Mapped[str] = mapped_column(String(256), nullable=False)
    suggestion: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
