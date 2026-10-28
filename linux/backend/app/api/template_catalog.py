from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.domain.errors import DomainError
from app.services.template_catalog_service import TemplateCatalogService, get_case_snapshot
from app.repositories import cases as case_repo

router = APIRouter(tags=['template-catalog'])


class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class TemplateCreateRequest(CatalogRequest):
    id: str = Field(min_length=1, max_length=64)
    backend_key: str = Field(alias='backendKey', min_length=1, max_length=64)
    catalog: dict
    structure: dict


class TemplateVersionRequest(CatalogRequest):
    structure: dict
    catalog: dict | None = None


class TemplateActiveRequest(CatalogRequest):
    active: bool


class TemplateSelectRequest(CatalogRequest):
    template_id: str | None = Field(default=None, alias='templateId')
    blank: bool = False


@router.get('/templates/catalog')
def catalog(db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).catalog()
    db.commit()
    return envelope(result)


@router.get('/templates')
def templates(include_disabled: bool = Query(False, alias='includeDisabled'), db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).catalog(include_disabled=include_disabled)
    db.commit()
    return envelope(result)


@router.post('/templates')
def create_template(body: TemplateCreateRequest, db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).create(template_id=body.id, backend_key=body.backend_key, catalog=body.catalog, structure=body.structure)
    db.commit()
    return envelope(result, '模板已创建')


@router.get('/templates/{template_id}')
def template_detail(template_id: str, db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).detail(template_id)
    db.commit()
    return envelope(result)


@router.get('/templates/{template_id}/versions')
def template_versions(template_id: str, db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).versions(template_id)
    db.commit()
    return envelope(result)


@router.post('/templates/{template_id}/versions')
def save_template_version(template_id: str, body: TemplateVersionRequest, db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).save_version(template_id, structure=body.structure, catalog=body.catalog)
    db.commit()
    return envelope(result, '已保存为新版本')


@router.patch('/templates/{template_id}')
def template_active(template_id: str, body: TemplateActiveRequest, db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).set_active(template_id, body.active)
    db.commit()
    return envelope(result, '模板状态已更新')


@router.post('/cases/{case_id}/template-selection')
def select_case_template(case_id: str, body: TemplateSelectRequest, db: Session = Depends(get_db)):
    result = TemplateCatalogService(db).select(case_id, template_id=body.template_id, blank=body.blank)
    db.commit()
    return envelope(result, '本案模板快照已保存')


@router.get('/cases/{case_id}/template-selection')
def case_template_selection(case_id: str, db: Session = Depends(get_db)):
    import json

    case_repo.get(db, case_id)
    row = get_case_snapshot(db, case_id)
    if row is None:
        raise DomainError('CASE_TEMPLATE_NOT_SELECTED', '本案尚未选择模板', 404)
    return envelope(dict(caseId=case_id, templateId=row.template_id, templateKey=row.template_key, versionId=row.version_id, blank=row.blank, snapshot=json.loads(row.snapshot_json)))
