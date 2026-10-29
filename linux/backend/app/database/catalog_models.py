from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # Vault 同步元数据。手工新建的条目 origin=manual，导入器永不覆盖。
    vault_uid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='faq')
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default='manual')
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)



class KnowledgeEntryVersion(TimestampMixin, Base):
    __tablename__ = 'knowledge_entry_versions'
    __table_args__ = (UniqueConstraint('entry_id', 'version', name='uq_knowledge_entry_version'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey('knowledge_entries.id'), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeEntryLink(Base):
    """Wiki 双链解析结果。目标条目尚未导入时 to_entry_id 为空，待下次解析。"""

    __tablename__ = 'knowledge_entry_links'
    __table_args__ = (UniqueConstraint('from_entry_id', 'target_title', name='uq_knowledge_link_target'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_entry_id: Mapped[str] = mapped_column(ForeignKey('knowledge_entries.id'), nullable=False, index=True)
    to_entry_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_entries.id'), nullable=True, index=True)
    target_title: Mapped[str] = mapped_column(String(256), nullable=False)
    relation: Mapped[str] = mapped_column(String(16), nullable=False, default='REFERENCES')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeSyncRun(Base):
    """一次 Vault 导入的记录。dry-run 也落一条，便于核对将要发生的变更。"""

    __tablename__ = 'knowledge_sync_runs'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_root: Mapped[str] = mapped_column(String(512), nullable=False)
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')


class AsrTermCorrection(TimestampMixin, Base):
    """同音/专名纠错表。wrong_text 唯一；停用条目的纠错项随之停用。"""

    __tablename__ = 'asr_term_corrections'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wrong_text: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    right_text: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default='TERM')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entry_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_entries.id'), nullable=True, index=True)

