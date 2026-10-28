from sqlalchemy import Boolean, ForeignKey, Integer, String
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
