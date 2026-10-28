from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utc_now


class DocumentExport(Base):
    __tablename__ = 'document_exports'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id'), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('document_snapshots.id'), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signature_manifest_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    fingerprint_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
