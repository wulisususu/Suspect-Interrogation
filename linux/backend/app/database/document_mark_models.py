from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utc_now


class DocumentFingerprint(Base):
    __tablename__ = 'document_fingerprints'
    __table_args__ = (UniqueConstraint('snapshot_id', name='uq_document_fingerprint_snapshot'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id'), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('document_snapshots.id'), nullable=False)
    image_data: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
