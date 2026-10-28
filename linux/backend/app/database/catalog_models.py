from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class RecordTemplate(TimestampMixin, Base):
    __tablename__ = 'record_templates'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    backend_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    catalog_json: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RecordTemplateVersion(TimestampMixin, Base):
    __tablename__ = 'record_template_versions'
    __table_args__ = (UniqueConstraint('template_id', 'version', name='uq_record_template_version'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey('record_templates.id'), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    structure_json: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_json: Mapped[str] = mapped_column(Text, nullable=False)


class CaseTemplateSnapshot(TimestampMixin, Base):
    __tablename__ = 'case_template_snapshots'

    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True)
    template_id: Mapped[str | None] = mapped_column(ForeignKey('record_templates.id'), nullable=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey('record_template_versions.id'), nullable=True)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    blank: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeCategory(TimestampMixin, Base):
    __tablename__ = 'knowledge_categories'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class KnowledgeEntry(TimestampMixin, Base):
    __tablename__ = 'knowledge_entries'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey('knowledge_categories.id'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class KnowledgeEntryVersion(TimestampMixin, Base):
    __tablename__ = 'knowledge_entry_versions'
    __table_args__ = (UniqueConstraint('entry_id', 'version', name='uq_knowledge_entry_version'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey('knowledge_entries.id'), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
