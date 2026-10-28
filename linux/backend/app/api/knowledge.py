from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
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


class EntryUpdateRequest(KnowledgeRequest):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    category_id: str | None = Field(default=None, alias='categoryId')
    content: str | None = Field(default=None, min_length=1, max_length=100000)
    keywords: list[str] | None = Field(default=None, max_length=100)
    active: bool | None = None


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
def entries(category_id: str | None = Query(None, alias='categoryId'), active: bool | None = None, q: str | None = None, db: Session = Depends(get_db)):
    result = KnowledgeService(db).entries(category_id=category_id, active=active, query=q)
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
