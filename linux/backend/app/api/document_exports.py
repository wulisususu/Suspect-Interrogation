from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.services.document_export_service import DocumentExportService, MEDIA_TYPES


router = APIRouter(tags=['document-exports'])


class ExportBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['DOCX', 'PDF']


def _service(request: Request, db: Session) -> DocumentExportService:
    return DocumentExportService(db, request.app.state.runtime_settings.data_dir)


@router.post('/cases/{case_id}/exports')
def create_export(case_id: str, body: ExportBody, request: Request, db: Session = Depends(get_db)):
    return envelope(_service(request, db).create(case_id, body.format))


@router.get('/cases/{case_id}/exports')
def list_exports(case_id: str, request: Request, limit: int = Query(100, ge=1, le=200),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return envelope(_service(request, db).list(case_id, limit=limit, offset=offset))


@router.get('/cases/{case_id}/exports/{export_id}/file')
def download_export(case_id: str, export_id: str, request: Request, db: Session = Depends(get_db)):
    path, metadata = _service(request, db).download(case_id, export_id)
    return FileResponse(path, media_type=MEDIA_TYPES[metadata['format']], filename=metadata['fileName'],
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
