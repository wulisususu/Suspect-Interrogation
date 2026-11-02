from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class CaseRecordingOptions(TimestampMixin, Base):
    __tablename__ = 'case_recording_options'

    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True)
    full_recording_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default='1')


class CaptureRecording(TimestampMixin, Base):
    __tablename__ = 'capture_recordings'

    capture_id: Mapped[str] = mapped_column(ForeignKey('asr_capture_sessions.id', ondelete='CASCADE'), primary_key=True)
    full_recording_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    original_sha256: Mapped[str | None] = mapped_column(String(64))
    original_sample_count: Mapped[int | None] = mapped_column(Integer)
    original_size_bytes: Mapped[int | None] = mapped_column(Integer)


class SessionRecordingSegment(TimestampMixin, Base):
    """通道②：一次「开始/继续询问 → 暂停/结束询问」之间的连续全程录音。"""

    __tablename__ = 'session_recording_segments'
    __table_args__ = (UniqueConstraint('case_id', 'ordinal', name='uq_session_recording_segments_case_ordinal'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id', ondelete='CASCADE'), nullable=False, index=True)
    interrogation_session_id: Mapped[str] = mapped_column(ForeignKey('interrogation_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    # RECORDING → CLOSING (暂停/结束后等浏览器送完尾音) → COMPLETE / EMPTY
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(32))
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    client_sample_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default='[]', server_default='[]')
    client_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='0')
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
