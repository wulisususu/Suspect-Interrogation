from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.services.recording_service import RecordingService, require_recording_actor

router = APIRouter(tags=['recordings'])


class RecordingOptionsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    full_recording_enabled: StrictBool = Field(alias='fullRecordingEnabled')


def service(request: Request, db: Session = Depends(get_db)):
    archive = getattr(request.app.state, 'recording_archive', None)
    coordinator = getattr(request.app.state, 'live_speech_coordinator', None)
    if archive is None and coordinator is not None:
        archive = coordinator.archive
    return RecordingService(db, archive)


@router.get('/cases/{case_id}/recording-options')
def get_options(case_id: str, recordings: RecordingService = Depends(service)):
    require_recording_actor()
    return envelope(recordings.options(case_id))


@router.patch('/cases/{case_id}/recording-options')
def set_options(case_id: str, body: RecordingOptionsRequest, recordings: RecordingService = Depends(service)):
    require_recording_actor()
    result = recordings.set_options(case_id, body.full_recording_enabled)
    recordings.db.commit()
    return envelope(result, '全程录音设置已保存')


@router.get('/cases/{case_id}/recordings')
def list_recordings(case_id: str, recordings: RecordingService = Depends(service)):
    return envelope(recordings.list_recordings(case_id))


@router.get('/cases/{case_id}/recordings/questions/{question_id}/captures/{capture_id}/audio')
def question_audio(case_id: str, question_id: str, capture_id: str, recordings: RecordingService = Depends(service)):
    path = recordings.question_audio(case_id, question_id, capture_id)
    recordings.db.commit()
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/cases/{case_id}/recordings/questions/{question_id}/captures/{capture_id}/fragments/{fragment_id}/audio')
def question_fragment_audio(case_id: str, question_id: str, capture_id: str, fragment_id: str, recordings: RecordingService = Depends(service)):
    path = recordings.question_audio(case_id, question_id, capture_id, fragment_id=fragment_id)
    recordings.db.commit()
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/cases/{case_id}/recordings/originals/{capture_id}/audio')
def original_audio(case_id: str, capture_id: str, reason: str = Query(min_length=1, max_length=1000), recordings: RecordingService = Depends(service)):
    path = recordings.original_audio(case_id, capture_id, reason=reason)
    recordings.db.commit()
    return FileResponse(path, media_type='audio/wav', filename=f'{capture_id}-original.wav', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
