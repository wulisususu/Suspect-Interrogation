from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.auth.context import current_actor_id
from app.services.knowledge_service import KnowledgeService

router = APIRouter(tags=['knowledge'])


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class CategoryRequest(KnowledgeRequest):
    name: str = Field(min_length=1, max_length=128)


class EntryCreateRequest(KnowledgeRequest):
    title: str = Field(min_length=1, max_length=256)
    category_id: str = Field(alias='categoryId')
    content: str = Field(min_length=1, max_length=100000)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    active: bool = True
    kind: str = 'faq'
    status: str = 'pending'
    source_ref: str | None = Field(default=None, alias='sourceRef', max_length=512)


class EntryUpdateRequest(KnowledgeRequest):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    category_id: str | None = Field(default=None, alias='categoryId')
    content: str | None = Field(default=None, min_length=1, max_length=100000)
    keywords: list[str] | None = Field(default=None, max_length=100)
    active: bool | None = None
    kind: str | None = None
    status: str | None = None
    source_ref: str | None = Field(default=None, alias='sourceRef', max_length=512)


class ImportRequest(KnowledgeRequest):
    root: str | None = None
    dry_run: bool = Field(default=True, alias='dryRun')


class DraftQuestionsRequest(KnowledgeRequest):
    case_id: str | None = Field(default=None, alias='caseId')
    question_id: str | None = Field(default=None, alias='questionId')
    element_key: str | None = Field(default=None, alias='elementKey')
    limit: int = Field(default=3, ge=1, le=10)


class TermCorrectionRequest(KnowledgeRequest):
    wrong: str = Field(min_length=1, max_length=128)
    right: str = Field(min_length=1, max_length=128)
    category: str = Field(default='TERM', max_length=32)
    active: bool = True
    replace: bool = False


class TermCorrectionPatch(KnowledgeRequest):
    active: bool


@router.get('/knowledge/categories')
def categories(db: Session = Depends(get_db)):
    result = KnowledgeService(db).categories()
    db.commit()
    return envelope(result)


@router.post('/knowledge/categories')
def create_category(body: CategoryRequest, db: Session = Depends(get_db)):
    result = KnowledgeService(db).create_category(body.name)
    db.commit()
    return envelope(result, '分类已创建')


@router.patch('/knowledge/categories/{category_id}')
def update_category(category_id: str, body: CategoryRequest, db: Session = Depends(get_db)):
    result = KnowledgeService(db).update_category(category_id, body.name)
    db.commit()
    return envelope(result, '分类已更新')


@router.delete('/knowledge/categories/{category_id}')
def delete_category(category_id: str, db: Session = Depends(get_db)):
    result = KnowledgeService(db).delete_category(category_id)
    db.commit()
    return envelope(result, '分类已移除')


@router.get('/knowledge/guidance')
def guidance(category_id: str | None = Query(None, alias='categoryId'), q: str | None = None, db: Session = Depends(get_db)):
    result = KnowledgeService(db).entries(category_id=category_id, query=q, guidance=True)
    db.commit()
    return envelope(result)


@router.get('/knowledge/entries')
def entries(category_id: str | None = Query(None, alias='categoryId'), active: bool | None = None,
            q: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    result = KnowledgeService(db).entries(category_id=category_id, active=active, query=q, status=status)
    db.commit()
    return envelope(result)


@router.post('/knowledge/entries')
def create_entry(body: EntryCreateRequest, db: Session = Depends(get_db)):
    result = KnowledgeService(db).create_entry(title=body.title, category_id=body.category_id, content=body.content, keywords=body.keywords, active=body.active)
    db.commit()
    return envelope(result, '条目已创建')


@router.get('/knowledge/entries/{entry_id}')
def entry(entry_id: str, db: Session = Depends(get_db)):
    return envelope(KnowledgeService(db).detail(entry_id))


@router.patch('/knowledge/entries/{entry_id}')
def update_entry(entry_id: str, body: EntryUpdateRequest, db: Session = Depends(get_db)):
    result = KnowledgeService(db).update_entry(entry_id, body.model_dump(exclude_unset=True, by_alias=True))
    db.commit()
    return envelope(result, '条目已更新')


@router.delete('/knowledge/entries/{entry_id}')
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    result = KnowledgeService(db).delete_entry(entry_id)
    db.commit()
    return envelope(result, '条目已删除，历史版本保留')


@router.get('/knowledge/entries/{entry_id}/versions')
def entry_versions(entry_id: str, db: Session = Depends(get_db)):
    return envelope(KnowledgeService(db).versions(entry_id))


@router.get('/knowledge/guidance/match')
def guidance_match(case_id: str | None = Query(None, alias='caseId'),
                   question_id: str | None = Query(None, alias='questionId'),
                   element_key: str | None = Query(None, alias='elementKey'),
                   q: str | None = None,
                   limit: int = Query(5, ge=1, le=20),
                   db: Session = Depends(get_db)):
    """按案件要素与当前题目匹配知识，供办案页实时提示。"""
    result = KnowledgeService(db).guidance_for(
        case_id=case_id, question_id=question_id, element_key=element_key, text=q, limit=limit,
    )
    db.commit()
    return envelope(result)


@router.post('/knowledge/draft-questions')
def draft_questions(body: DraftQuestionsRequest, db: Session = Depends(get_db)):
    """给出建议问法。只返回候选，不建题、不写笔录。"""
    result = KnowledgeService(db).draft_questions(
        case_id=body.case_id, question_id=body.question_id, element_key=body.element_key, limit=body.limit,
    )
    db.commit()
    return envelope(result)


@router.get('/knowledge/entries/{entry_id}/links')
def entry_links(entry_id: str, db: Session = Depends(get_db)):
    return envelope(KnowledgeService(db).links(entry_id))


def _vault_root(request: Request, override: str | None):
    from pathlib import Path

    if override:
        return Path(override)
    settings = getattr(request.app.state, 'runtime_settings', None)
    configured = getattr(settings, 'knowledge_vault_dir', None)
    if configured is not None:
        return Path(configured)
    return Path.cwd() / 'obsidian-vault'


@router.post('/knowledge/import')
def import_vault(body: ImportRequest, request: Request, db: Session = Depends(get_db)):
    service = KnowledgeService(db)
    result = service.import_vault(_vault_root(request, body.root), dry_run=body.dry_run, actor_id=current_actor_id())
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return envelope(result, '导入预演完成' if body.dry_run else '知识库已导入')


@router.get('/knowledge/import/runs')
def import_runs(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    return envelope(KnowledgeService(db).sync_runs(limit))


@router.get('/knowledge/term-corrections')
def term_corrections(active: bool | None = None, db: Session = Depends(get_db)):
    return envelope(KnowledgeService(db).term_corrections(active=active))


@router.get('/knowledge/term-corrections/lookup')
def term_correction_lookup(text: str = Query(..., min_length=1, max_length=2000), db: Session = Depends(get_db)):
    return envelope(KnowledgeService(db).lookup_corrections(text))


@router.get('/knowledge/term-corrections/export')
def term_correction_export(db: Session = Depends(get_db)):
    """导出 asr-stack 的 corrections.json 结构与热词列表（部署时写入板端）。"""
    return envelope(KnowledgeService(db).export_corrections())


@router.post('/knowledge/term-corrections')
def term_correction_create(body: TermCorrectionRequest, db: Session = Depends(get_db)):
    result = KnowledgeService(db).upsert_term_correction(
        wrong=body.wrong, right=body.right, category=body.category, active=body.active, replace=body.replace,
    )
    db.commit()
    return envelope(result, '热词已保存')


@router.patch('/knowledge/term-corrections/{correction_id}')
def term_correction_patch(correction_id: str, body: TermCorrectionPatch, db: Session = Depends(get_db)):
    result = KnowledgeService(db).set_term_correction_active(correction_id, body.active)
    db.commit()
    return envelope(result, '热词状态已更新')
