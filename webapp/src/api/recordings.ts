import { http } from './http'

export interface RecordingQuestion {
  questionId: string
  questionNumber: number | null
  question: string
  questionActive: boolean
  captureSessionId: string
  fragmentId: string | null
  startSample: number
  endSample: number
  startMs: number
  durationMs: number
  startedAt: string | null
  status: string
  available: boolean
  audioUrl: string | null
}

export interface RecordingOriginal {
  captureSessionId: string
  filename: string
  durationMs: number
  sizeBytes: number
  sha256: string
  startedAt: string | null
  accessRequiresAdmin: boolean
}

export interface RecordingOptions {
  caseId: string
  fullRecordingEnabled: boolean
}

export interface CaseRecordings extends RecordingOptions {
  questions: RecordingQuestion[]
  originals: RecordingOriginal[]
  originalAccessRequiresAdmin: boolean
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    const envelope = payload as { ok: boolean; data?: T; code?: string; message?: string }
    if (!envelope.ok) throw new Error(envelope.message || envelope.code || '录音接口返回错误')
    return ('data' in envelope ? envelope.data : payload) as T
  }
  return payload as T
}

export async function fetchCaseRecordings(caseId: string): Promise<CaseRecordings> {
  const response = await http.get(`/api/v1/cases/${encodeURIComponent(caseId)}/recordings`)
  return unwrap<CaseRecordings>(response.data)
}

export async function updateRecordingOptions(caseId: string, fullRecordingEnabled: boolean): Promise<RecordingOptions> {
  const response = await http.patch(`/api/v1/cases/${encodeURIComponent(caseId)}/recording-options`, {
    fullRecordingEnabled,
  })
  return unwrap<RecordingOptions>(response.data)
}

/** 通道①：某题某次采集（或片段）的音频地址，直接用 <audio> 播放，浏览器会带上会话 Cookie。 */
export function questionAudioUrl(recordings: CaseRecordings, row: RecordingQuestion): string | null {
  if (!row.audioUrl) return null
  return `/api/v1/cases/${encodeURIComponent(recordings.caseId)}/recordings/questions/`
    + `${encodeURIComponent(row.questionId)}/captures/${encodeURIComponent(row.captureSessionId)}`
    + `${row.fragmentId ? `/fragments/${encodeURIComponent(row.fragmentId)}` : ''}/audio`
}

/** 通道②：全程原始录音，必须带调阅原因；服务端会写审计并要求管理员。 */
export function originalAudioUrl(caseId: string, captureId: string, reason: string): string {
  return `/api/v1/cases/${encodeURIComponent(caseId)}/recordings/originals/`
    + `${encodeURIComponent(captureId)}/audio?reason=${encodeURIComponent(reason)}`
}
