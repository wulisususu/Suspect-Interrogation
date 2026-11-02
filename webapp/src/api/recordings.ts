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

export interface RecordingSegmentGap {
  /** 缺口出现在文件里的第几毫秒 */
  atMs: number
  /** 估计缺了多久；null 表示无法估计 */
  missingMs: number | null
  reason: 'BROWSER_BUFFER_DROPPED' | 'BROWSER_RESTARTED' | string
  at: string | null
}

/** 通道②：一次「开始/继续询问 → 暂停/结束询问」的连续全程录音。 */
export interface RecordingSegment {
  segmentId: string
  ordinal: number
  sessionId: string
  status: 'RECORDING' | 'CLOSING' | 'COMPLETE' | 'EMPTY' | string
  startedAt: string | null
  endedAt: string | null
  endReason: string | null
  durationMs: number
  sizeBytes: number | null
  sha256: string | null
  filename: string
  gaps: RecordingSegmentGap[]
  tailConfirmed: boolean
  available: boolean
  accessRequiresAdmin: boolean
}

export interface RecordingOptions {
  caseId: string
  fullRecordingEnabled: boolean
}

export interface CaseRecordings extends RecordingOptions {
  questions: RecordingQuestion[]
  segments?: RecordingSegment[]
  /** 按次采集的原始文件；全程录音上线前的案件只有这一种。 */
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

/** 通道②：一段全程录音，同样必须带调阅原因并由管理员调阅。 */
export function segmentAudioUrl(caseId: string, segmentId: string, reason: string): string {
  return `/api/v1/cases/${encodeURIComponent(caseId)}/recordings/segments/`
    + `${encodeURIComponent(segmentId)}/audio?reason=${encodeURIComponent(reason)}`
}
