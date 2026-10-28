"""Officer identity is independent of the retired voiceprint library."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, utc_now


class Officer(TimestampMixin, Base):
    __tablename__ = 'officers'

    badge_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(256), default='', nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    login_blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OfficerSession(Base):
    __tablename__ = 'officer_sessions'

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    badge_number: Mapped[str] = mapped_column(ForeignKey('officers.badge_number', ondelete='CASCADE'), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    exemption_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CaseOfficerBinding(TimestampMixin, Base):
    __tablename__ = 'case_officer_bindings'

    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True)
    interrogator_badge_number: Mapped[str | None] = mapped_column(ForeignKey('officers.badge_number'), nullable=True)
    recorder_badge_number: Mapped[str | None] = mapped_column(ForeignKey('officers.badge_number'), nullable=True)


class OfficerSignature(Base):
    __tablename__ = 'officer_signatures'
    __table_args__ = (UniqueConstraint('badge_number', 'version', name='uq_officer_signature_version'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    badge_number: Mapped[str] = mapped_column(ForeignKey('officers.badge_number'), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    image_data: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OfficerSignatureUse(Base):
    __tablename__ = 'officer_signature_uses'
    __table_args__ = (UniqueConstraint('signature_record_id', name='uq_officer_signature_use_record'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id'), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('document_snapshots.id'), nullable=False)
    signature_record_id: Mapped[str] = mapped_column(ForeignKey('signature_records.id'), nullable=False)
    officer_signature_id: Mapped[str] = mapped_column(ForeignKey('officer_signatures.id'), nullable=False, index=True)
    badge_number: Mapped[str] = mapped_column(ForeignKey('officers.badge_number'), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
