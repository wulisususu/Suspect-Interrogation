from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    DDL,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, utc_now
from app.domain.enums import InterrogationStage, SessionStatus, WorkflowState


class Case(TimestampMixin, Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    case_type: Mapped[str] = mapped_column(String(64), default="suspect_interrogation", nullable=False)
    suspect_name: Mapped[str] = mapped_column(String(128), default="待录入", nullable=False)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age: Mapped[str | None] = mapped_column(String(32), nullable=True)
    officer_name: Mapped[str] = mapped_column(String(128), default="当前警官", nullable=False)
    workflow_state: Mapped[str] = mapped_column(String(32), default=WorkflowState.IDENTITY_REQUIRED.value, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), default=InterrogationStage.IDENTITY.value, nullable=False)
    document_status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    report_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)

    persons = relationship("Person", back_populates="case", cascade="all, delete-orphan")
    sessions = relationship("InterrogationSession", back_populates="case", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="case", cascade="all, delete-orphan")


class Person(TimestampMixin, Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="suspect", nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    id_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="idcard", nullable=False)

    case = relationship("Case", back_populates="persons")


class InterrogationSession(TimestampMixin, Base):
    __tablename__ = "interrogation_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default=SessionStatus.READY.value, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), default=InterrogationStage.IDENTITY.value, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case = relationship("Case", back_populates="sessions")
    messages = relationship("Message", back_populates="session")


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("case_id", "seq", name="uq_messages_case_seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    mark: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    case = relationship("Case", back_populates="messages")
    session = relationship("InterrogationSession", back_populates="messages")
    revisions = relationship("MessageRevision", back_populates="message", cascade="all, delete-orphan")


class MessageRevision(Base):
    __tablename__ = "message_revisions"
    __table_args__ = (UniqueConstraint("message_id", "version", name="uq_message_revision_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    old_text: Mapped[str] = mapped_column(Text, nullable=False)
    new_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    message = relationship("Message", back_populates="revisions")


class Fact(TimestampMixin, Base):
    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("case_id", "fact_key", name="uq_fact_case_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    fact_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)


class TimelineEvent(Base):
    """Legacy case-overview table. The feature was removed, but the model must
    stay: alembic revision 0001 creates tables from Base.metadata, so dropping
    this class would break the historical migration chain. No code reads or
    writes this table anymore.
    """

    __tablename__ = "timeline_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    time_label: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    after_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class DeviceEvent(Base):
    __tablename__ = "device_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True)
    device: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class DocumentSnapshot(Base):
    __tablename__ = "document_snapshots"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_document_case_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="FROZEN", nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SignatureRecord(Base):
    __tablename__ = "signature_records"
    __table_args__ = (UniqueConstraint("snapshot_id", "signer_role", name="uq_signature_snapshot_role"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("document_snapshots.id", ondelete="SET NULL"), nullable=True)
    signer_role: Mapped[str] = mapped_column(String(64), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    image_data: Mapped[str] = mapped_column(Text, nullable=False)
    strokes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="SAVED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SuspectVoiceprint(TimestampMixin, Base):
    __tablename__ = "suspect_voiceprints"
    __table_args__ = (UniqueConstraint("case_id", "model_key", name="uq_suspect_voiceprint_case_model"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    model_key: Mapped[str] = mapped_column(String(64), default="eres2net_large", nullable=False, index=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enrollment_quality: Mapped[str] = mapped_column(String(64), nullable=False)
    usable_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OfficerVoiceprint(TimestampMixin, Base):
    __tablename__ = "officer_voiceprints"
    __table_args__ = (UniqueConstraint("officer_id", "model_key", name="uq_officer_voiceprint_officer_model"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    officer_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_key: Mapped[str] = mapped_column(String(64), default="eres2net_large", nullable=False, index=True)
    officer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enrollment_quality: Mapped[str] = mapped_column(String(64), nullable=False)
    usable_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseVoiceRoleDraft(TimestampMixin, Base):
    __tablename__ = "case_voice_role_drafts"
    __table_args__ = (UniqueConstraint("case_id", name="uq_case_voice_role_draft_case"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    interrogator_officer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorder_officer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class SessionVoiceAssignment(TimestampMixin, Base):
    __tablename__ = "session_voice_assignments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interrogation_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    suspect_voiceprint_id: Mapped[str] = mapped_column(
        ForeignKey("suspect_voiceprints.id", ondelete="RESTRICT"), nullable=False
    )
    interrogator_officer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    interrogator_voiceprint_id: Mapped[str | None] = mapped_column(
        ForeignKey("officer_voiceprints.id", ondelete="RESTRICT"), nullable=True
    )
    recorder_officer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorder_voiceprint_id: Mapped[str | None] = mapped_column(
        ForeignKey("officer_voiceprints.id", ondelete="RESTRICT"), nullable=True
    )
    recognition_mode: Mapped[str] = mapped_column(String(64), nullable=False)


class ASRCaptureSession(Base):
    __tablename__ = "asr_capture_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    interrogation_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    target_question_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replace_answer: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    answer_replacement_applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    audio_sample_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    asr_cursor_sample: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    asr_finalize_checkpoint_sample: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asr_unfinished_start_sample: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voiced_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    recording_status: Mapped[str] = mapped_column(String(32), default="PENDING", server_default="PENDING", nullable=False)
    asr_status: Mapped[str] = mapped_column(String(32), default="PENDING", server_default="PENDING", nullable=False)
    speaker_status: Mapped[str] = mapped_column(String(32), default="PENDING", server_default="PENDING", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ASRFragment(TimestampMixin, Base):
    __tablename__ = "asr_fragments"
    __table_args__ = (
        UniqueConstraint("capture_session_id", "ordinal", name="uq_asr_fragments_capture_ordinal"),
        UniqueConstraint("asr_idempotency_key", name="uq_asr_fragments_asr_idempotency_key"),
        CheckConstraint("state != 'SUPERSEDED' OR confirmed_message_id IS NULL", name="ck_asr_fragments_superseded_unconfirmed"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capture_session_id: Mapped[str] = mapped_column(
        ForeignKey("asr_capture_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    edited_text: Mapped[str] = mapped_column(Text, nullable=False)
    asr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker: Mapped[str] = mapped_column(String(32), nullable=False)
    speaker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    speaker_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    speaker_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_source: Mapped[str] = mapped_column(String(64), nullable=False)
    voiceprint_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asr_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )


event.listen(
    ASRFragment.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER tr_asr_fragments_superseded_unconfirmed_insert "
        "BEFORE INSERT ON asr_fragments "
        "WHEN NEW.state = 'SUPERSEDED' AND NEW.confirmed_message_id IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'confirmed fragments cannot be superseded'); END"
    ).execute_if(dialect="sqlite"),
)
event.listen(
    ASRFragment.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER tr_asr_fragments_superseded_unconfirmed_update "
        "BEFORE UPDATE OF state, confirmed_message_id ON asr_fragments "
        "WHEN NEW.state = 'SUPERSEDED' AND (OLD.state = 'CONFIRMED' OR NEW.confirmed_message_id IS NOT NULL) "
        "BEGIN SELECT RAISE(ABORT, 'confirmed fragments cannot be superseded'); END"
    ).execute_if(dialect="sqlite"),
)


class ASRAudioSegment(TimestampMixin, Base):
    __tablename__ = "asr_audio_segments"
    __table_args__ = (UniqueConstraint("capture_session_id", "sequence", name="uq_asr_audio_segments_capture_sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capture_session_id: Mapped[str] = mapped_column(
        ForeignKey("asr_capture_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    start_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    committed_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    finalized_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)


class ASRAudioFrame(Base):
    __tablename__ = "asr_audio_frames"
    __table_args__ = (UniqueConstraint("capture_session_id", "source_sequence", name="uq_asr_audio_frames_capture_source_sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capture_session_id: Mapped[str] = mapped_column(
        ForeignKey("asr_capture_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    end_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    durable_sample_end: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LiveSpeechJob(TimestampMixin, Base):
    __tablename__ = "live_speech_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_live_speech_jobs_idempotency_key"),
        CheckConstraint("kind IN ('ASR', 'SPEAKER')", name="ck_live_speech_jobs_kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    capture_session_id: Mapped[str] = mapped_column(
        ForeignKey("asr_capture_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fragment_id: Mapped[str | None] = mapped_column(
        ForeignKey("asr_fragments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    start_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    end_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ASRFragmentLineage(Base):
    __tablename__ = "asr_fragment_lineage"
    __table_args__ = (
        UniqueConstraint("parent_fragment_id", "child_fragment_id", name="uq_asr_fragment_lineage_parent_child"),
        CheckConstraint("relation = 'SUPERSEDES'", name="ck_asr_fragment_lineage_relation"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_job_id: Mapped[str] = mapped_column(
        ForeignKey("live_speech_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_fragment_id: Mapped[str] = mapped_column(
        ForeignKey("asr_fragments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_fragment_id: Mapped[str] = mapped_column(
        ForeignKey("asr_fragments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation: Mapped[str] = mapped_column(String(32), default="SUPERSEDES", server_default="SUPERSEDES", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class StandardQuestion(TimestampMixin, Base):
    __tablename__ = "standard_questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="通用", nullable=False, index=True)
    regex_patterns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CaseQuestion(TimestampMixin, Base):
    __tablename__ = "case_questions"
    __table_args__ = (UniqueConstraint("case_id", "sort_order", name="uq_case_questions_sort"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    standard_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("standard_questions.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    regex_patterns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    section_type: Mapped[str] = mapped_column(String(16), default="BODY", nullable=False, index=True)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    template_item_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    element_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    formal_answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    first_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class QuestionRound(TimestampMixin, Base):
    __tablename__ = "question_rounds"
    __table_args__ = (UniqueConstraint("case_question_id", "round_no", name="uq_question_round_no"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    case_question_id: Mapped[str] = mapped_column(
        ForeignKey("case_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_question_text: Mapped[str] = mapped_column(Text, nullable=False)
    officer_fragment_id: Mapped[str | None] = mapped_column(
        ForeignKey("asr_fragments.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answer_fragment_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PendingQuestion(TimestampMixin, Base):
    __tablename__ = "pending_questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    officer_fragment_id: Mapped[str] = mapped_column(
        ForeignKey("asr_fragments.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    match_status: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_question_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    buffered_answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    buffered_fragment_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False, index=True)


class ProcessedSpeechFragment(Base):
    __tablename__ = "processed_speech_fragments"

    fragment_id: Mapped[str] = mapped_column(
        ForeignKey("asr_fragments.id", ondelete="CASCADE"), primary_key=True
    )
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class QAUnit(TimestampMixin, Base):
    __tablename__ = "qa_units"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interrogation_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False, index=True)
    raw_question_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("case_questions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    formal_question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    formal_answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_question_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    fragments = relationship(
        "QAUnitFragment",
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="QAUnitFragment.position",
    )


class QAUnitFragment(Base):
    __tablename__ = "qa_unit_fragments"
    __table_args__ = (
        UniqueConstraint("fragment_id", name="uq_qa_unit_fragments_fragment_id"),
        UniqueConstraint("qa_unit_id", "position", name="uq_qa_unit_fragments_position"),
    )

    qa_unit_id: Mapped[str] = mapped_column(ForeignKey("qa_units.id", ondelete="CASCADE"), primary_key=True)
    fragment_id: Mapped[str] = mapped_column(ForeignKey("asr_fragments.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    unit = relationship("QAUnit", back_populates="fragments")
