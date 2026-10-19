import type { AxiosError } from 'axios'
import {
  getRuntimeAdapter,
  RuntimeAdapterError,
  type RuntimeCapabilities,
  type RuntimeEventListener,
  type RuntimeSessionConnection,
} from '../runtime'
import type {
  AsrCaptureStatus,
  AsrRecognitionEvidence,
  AsrRecognitionRevision,
  AsrRuntimeStatus,
  CaseAiAnalysis,
  CaseSummary,
  DeviceActionResult,
  FactItem,
  InquirySsePayload,
  InterrogationStage,
  LlmGenerateRequest,
  LlmResult,
  LlmRuntimeStatus,
  LocalModelCatalog,
  ModelCategory,
  ModelImportSource,
  OcrResult,
  OcrRuntimeStatus,
  OfficerVoiceprint,
  RecordMark,
  RecordRevision,
  SessionState,
  SessionStatus,
  TemporaryAsrFragment,
  TemporaryAsrSpeaker,
  TranscriptMessage,
  VoiceprintCaptureStatus,
  VoiceprintEnrollmentResult,
  VoiceprintReadiness,
  VoiceprintRoleDraft,
  VoiceRecognitionMode,
} from '../types/interrogation'

const runtime = () => getRuntimeAdapter()

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function toTimestamp(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const isIsoDateTime = /^\d{4}-\d{2}-\d{2}T/.test(value)
    const hasTimezone = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(value)
    const parsed = Date.parse(isIsoDateTime && !hasTimezone ? `${value}Z` : value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeCaseSummary(value: unknown, fallback: Partial<CaseSummary> = {}): CaseSummary {
  const raw = asRecord(value)
  const id = String(raw.id ?? raw.case_id ?? fallback.id ?? '')
  return {
    ...fallback,
    id,
    suspectName: String(raw.suspectName ?? raw.suspect_name ?? fallback.suspectName ?? ''),
    gender: raw.gender === undefined ? fallback.gender : String(raw.gender),
    age: raw.age === undefined ? fallback.age : String(raw.age),
    idNumber: raw.idNumber === undefined && raw.id_number === undefined ? fallback.idNumber : String(raw.idNumber ?? raw.id_number ?? ''),
    nation: raw.nation === undefined ? fallback.nation : String(raw.nation),
    birthDate: raw.birthDate === undefined && raw.birth_date === undefined ? fallback.birthDate : String(raw.birthDate ?? raw.birth_date ?? ''),
    address: raw.address === undefined ? fallback.address : String(raw.address),
    identitySource: raw.identitySource === undefined && raw.identity_source === undefined ? fallback.identitySource : String(raw.identitySource ?? raw.identity_source),
    identityCapturedAt: toTimestamp(raw.identityCapturedAt ?? raw.identity_captured_at) ?? fallback.identityCapturedAt,
    officerName: String(raw.officerName ?? raw.operator_id ?? raw.officer_name ?? fallback.officerName ?? '当前警官'),
    state: String(raw.state ?? fallback.state ?? 'DRAFT'),
    workflowState: raw.workflowState == null && raw.workflow_state == null ? fallback.workflowState : String(raw.workflowState ?? raw.workflow_state),
    documentStatus: raw.documentStatus == null && raw.document_status == null ? fallback.documentStatus : String(raw.documentStatus ?? raw.document_status),
    reportStatus: raw.reportStatus == null && raw.report_status == null ? fallback.reportStatus : String(raw.reportStatus ?? raw.report_status),
    caseType: raw.caseType == null && raw.case_type == null ? fallback.caseType : String(raw.caseType ?? raw.case_type),
    stage: (raw.stage ?? fallback.stage ?? 'IDENTITY') as InterrogationStage,
    createdAt: toTimestamp(raw.createdAt ?? raw.created_at) ?? fallback.createdAt,
    updatedAt: toTimestamp(raw.updatedAt ?? raw.updated_at) ?? fallback.updatedAt,
  }
}

function normalizeSessionState(value: unknown, caseId: string): SessionState {
  const raw = asRecord(value)
  const backendState = String(raw.status ?? raw.state ?? 'READY').toUpperCase()
  const statusMap: Record<string, SessionStatus> = {
    READY: 'READY', QUESTIONING: 'RUNNING', RUNNING: 'RUNNING', PAUSED: 'PAUSED', SUMMARY: 'COMPLETED', COMPLETED: 'COMPLETED',
  }
  return {
    id: raw.id === null ? null : String(raw.id ?? raw.session_id ?? '') || null,
    caseId: String(raw.caseId ?? raw.case_id ?? caseId),
    status: statusMap[backendState] || 'READY',
    stage: (raw.stage ?? (backendState === 'SUMMARY' ? 'SIGNING' : 'IDENTITY')) as InterrogationStage,
    startedAt: toTimestamp(raw.startedAt ?? raw.started_at) ?? null,
    pausedAt: toTimestamp(raw.pausedAt ?? raw.paused_at) ?? null,
    endedAt: toTimestamp(raw.endedAt ?? raw.ended_at) ?? null,
    updatedAt: toTimestamp(raw.updatedAt ?? raw.updated_at) ?? Date.now(),
  }
}

function normalizeVoiceprintReadiness(value: unknown): VoiceprintReadiness {
  const raw = asRecord(value)
  const mode = String(raw.recognitionMode ?? 'SUSPECT_ONLY') as VoiceRecognitionMode
  const declared = raw.declaredRecognitionMode === undefined
    ? undefined
    : String(raw.declaredRecognitionMode) as VoiceRecognitionMode
  // Task 17B-1: the backend reports null for both fields when it cannot verify the
  // runtime operating point. "Unverified" is carried by recognitionModeVerified=false,
  // and the mode claim is simply not reported, so null maps to absent instead of being
  // coerced into a claim ("null" as a mode, or null -> false = "not degraded").
  const effective = raw.effectiveRecognitionMode === undefined
    ? undefined
    : (raw.effectiveRecognitionMode === null
      ? undefined
      : String(raw.effectiveRecognitionMode) as VoiceRecognitionMode)
  const degraded = raw.recognitionModeDegraded === undefined
    ? undefined
    : (raw.recognitionModeDegraded === null ? undefined : Boolean(raw.recognitionModeDegraded))
  const degradedReason = raw.recognitionModeDegradedReason === undefined ? undefined : String(raw.recognitionModeDegradedReason)
  return {
    suspectReady: Boolean(raw.suspectReady),
    interrogatorReady: Boolean(raw.interrogatorReady),
    recorderReady: Boolean(raw.recorderReady),
    recognitionMode: mode,
    canStart: Boolean(raw.canStart),
    ...(raw.simulated === undefined ? {} : { simulated: Boolean(raw.simulated) }),
    // Task 17B-1: registration metrics and the runtime speaker operating point must
    // survive normalization, otherwise the card can never prove the effective mode.
    ...(raw.enrollmentQuality === undefined ? {} : { enrollmentQuality: raw.enrollmentQuality === null ? null : String(raw.enrollmentQuality) }),
    ...(raw.usableDurationMs === undefined ? {} : { usableDurationMs: nullableNumber(raw.usableDurationMs) }),
    ...(raw.modelKey === undefined ? {} : { modelKey: raw.modelKey === null ? null : String(raw.modelKey) }),
    ...(raw.modelId === undefined ? {} : { modelId: raw.modelId === null ? null : String(raw.modelId) }),
    ...(raw.modelVersion === undefined ? {} : { modelVersion: raw.modelVersion === null ? null : String(raw.modelVersion) }),
    ...(raw.speakerMargin === undefined ? {} : { speakerMargin: nullableNumber(raw.speakerMargin) }),
    ...(raw.speakerThreshold === undefined ? {} : { speakerThreshold: nullableNumber(raw.speakerThreshold) }),
    ...(raw.thresholdSource === undefined ? {} : { thresholdSource: raw.thresholdSource === null ? null : String(raw.thresholdSource) }),
    ...(raw.marginConfigured === undefined ? {} : { marginConfigured: Boolean(raw.marginConfigured) }),
    ...(raw.thresholdConfigured === undefined ? {} : { thresholdConfigured: Boolean(raw.thresholdConfigured) }),
    ...(declared === undefined ? {} : { declaredRecognitionMode: declared }),
    ...(effective === undefined ? {} : { effectiveRecognitionMode: effective }),
    ...(degraded === undefined ? {} : { recognitionModeDegraded: degraded }),
    ...(degradedReason === undefined ? {} : { recognitionModeDegradedReason: degradedReason }),
    ...(raw.recognitionModeVerified === undefined ? {} : { recognitionModeVerified: Boolean(raw.recognitionModeVerified) }),
    ...(raw.recognitionModeVerificationSource === undefined || raw.recognitionModeVerificationSource === null
      ? {}
      : { recognitionModeVerificationSource: String(raw.recognitionModeVerificationSource) }),
  }
}

function normalizeVoiceprintRoleDraft(value: unknown): VoiceprintRoleDraft {
  const raw = asRecord(value)
  return {
    caseId: String(raw.caseId ?? raw.case_id ?? ''),
    interrogatorOfficerId: raw.interrogatorOfficerId == null && raw.interrogator_officer_id == null
      ? null
      : String(raw.interrogatorOfficerId ?? raw.interrogator_officer_id),
    recorderOfficerId: raw.recorderOfficerId == null && raw.recorder_officer_id == null
      ? null
      : String(raw.recorderOfficerId ?? raw.recorder_officer_id),
  }
}

function normalizeVoiceprintCaptureStatus(value: unknown): VoiceprintCaptureStatus {
  const raw = asRecord(value)
  return {
    active: Boolean(raw.active),
    kind: raw.kind == null ? null : String(raw.kind),
    subjectId: raw.subjectId == null ? null : String(raw.subjectId),
    capturedDurationMs: Number(raw.capturedDurationMs ?? 0),
    targetDurationMs: Number(raw.targetDurationMs ?? 30000),
    complete: Boolean(raw.complete),
  }
}

function normalizeOfficerVoiceprint(value: unknown): OfficerVoiceprint {
  const raw = asRecord(value)
  return {
    voiceprintId: raw.voiceprintId == null ? undefined : String(raw.voiceprintId),
    officerId: String(raw.officerId ?? ''),
    officerName: String(raw.officerName ?? ''),
    active: Boolean(raw.active),
    modelId: String(raw.modelId ?? ''),
    modelVersion: raw.modelVersion == null ? null : String(raw.modelVersion),
    enrollmentQuality: String(raw.enrollmentQuality ?? raw.quality ?? ''),
    usableDurationMs: Number(raw.usableDurationMs ?? 0),
    revokedAt: raw.revokedAt == null ? null : String(raw.revokedAt),
    ...(raw.simulated === undefined ? {} : { simulated: Boolean(raw.simulated) }),
  }
}

function normalizeRecognitionEvidence(value: unknown): AsrRecognitionEvidence | null {
  if (!value || typeof value !== 'object') return null
  const raw = asRecord(value)
  const evidenceId = String(raw.evidenceId ?? '')
  if (!evidenceId) return null
  return {
    evidenceId,
    aiSpeaker: String(raw.aiSpeaker ?? 'UNKNOWN') as TemporaryAsrSpeaker,
    speakerId: raw.speakerId == null ? null : String(raw.speakerId),
    speakerName: raw.speakerName == null ? null : String(raw.speakerName),
    speakerSource: String(raw.speakerSource ?? 'UNASSIGNED') as AsrRecognitionEvidence['speakerSource'],
    score: nullableNumber(raw.score),
    secondBestScore: nullableNumber(raw.secondBestScore),
    threshold: nullableNumber(raw.threshold),
    margin: nullableNumber(raw.margin),
    thresholdSource: raw.thresholdSource == null ? null : String(raw.thresholdSource),
    voiceprintVerified: Boolean(raw.voiceprintVerified),
    lowConfidence: Boolean(raw.lowConfidence),
    asrModelId: raw.asrModelId == null ? null : String(raw.asrModelId),
    asrModelVersion: raw.asrModelVersion == null ? null : String(raw.asrModelVersion),
    speakerModelId: raw.speakerModelId == null ? null : String(raw.speakerModelId),
    speakerModelVersion: raw.speakerModelVersion == null ? null : String(raw.speakerModelVersion),
    speakerModelFingerprint: raw.speakerModelFingerprint == null ? null : String(raw.speakerModelFingerprint),
    microphoneFingerprint: raw.microphoneFingerprint == null ? null : String(raw.microphoneFingerprint),
    calibrationId: raw.calibrationId == null ? null : String(raw.calibrationId),
    calibrationStatus: raw.calibrationStatus == null ? null : String(raw.calibrationStatus),
    createdAt: toTimestamp(raw.createdAt) ?? null,
  }
}

function normalizeRecognitionRevision(value: unknown): AsrRecognitionRevision {
  const raw = asRecord(value)
  return {
    revisionId: String(raw.revisionId ?? ''),
    revisionNo: Number(raw.revisionNo ?? 0),
    beforeSpeaker: String(raw.beforeSpeaker ?? 'UNKNOWN') as TemporaryAsrSpeaker,
    afterSpeaker: String(raw.afterSpeaker ?? 'UNKNOWN') as TemporaryAsrSpeaker,
    beforeText: String(raw.beforeText ?? ''),
    afterText: String(raw.afterText ?? ''),
    actorId: raw.actorId == null ? null : String(raw.actorId),
    reason: raw.reason == null ? null : String(raw.reason),
    createdAt: toTimestamp(raw.createdAt) ?? null,
  }
}

/**
 * Task 17B-1: the mode an ASR fragment was decided in, as published on ASR_FRAGMENT.
 * Only copied when the backend sent it, so an older payload keeps the fields absent.
 */
function modeFields(raw: Record<string, unknown>): Partial<TemporaryAsrFragment> {
  return {
    ...(raw.declaredRecognitionMode === undefined || raw.declaredRecognitionMode === null
      ? {}
      : { declaredRecognitionMode: String(raw.declaredRecognitionMode) as VoiceRecognitionMode }),
    ...(raw.effectiveRecognitionMode === undefined || raw.effectiveRecognitionMode === null
      ? {}
      : { effectiveRecognitionMode: String(raw.effectiveRecognitionMode) as VoiceRecognitionMode }),
    ...(raw.recognitionModeDegraded === undefined || raw.recognitionModeDegraded === null
      ? {}
      : { recognitionModeDegraded: Boolean(raw.recognitionModeDegraded) }),
    ...(raw.recognitionModeDegradedReason === undefined || raw.recognitionModeDegradedReason === null
      ? {}
      : { recognitionModeDegradedReason: String(raw.recognitionModeDegradedReason) }),
  }
}

export function normalizeTemporaryAsrFragment(value: unknown): TemporaryAsrFragment {
  const raw = asRecord(value)
  const startedAtMs = Number(raw.startedAtMs ?? 0)
  const endedAtMs = Number(raw.endedAtMs ?? startedAtMs)
  const captureSessionId = String(raw.captureSessionId ?? '')
  const captureStartedAt = toTimestamp(raw.captureStartedAt ?? raw.capture_started_at)
  const createdAt = toTimestamp(raw.createdAt ?? raw.created_at) ?? Date.now()
  const updatedAt = toTimestamp(raw.updatedAt ?? raw.updated_at) ?? createdAt
  const confidence = nullableNumber(raw.asrConfidence ?? raw.confidence)
  const recognitionRevisions = Array.isArray(raw.recognitionRevisions)
    ? raw.recognitionRevisions.map(normalizeRecognitionRevision)
    : []
  return {
    id: String(raw.id ?? raw.fragmentId ?? ''),
    captureSessionId,
    caseId: String(raw.caseId ?? ''),
    ordinal: Number(raw.ordinal ?? 0),
    captureStartedAt: captureStartedAt ?? null,
    startedAtMs,
    endedAtMs,
    rawText: String(raw.rawText ?? ''),
    editedText: String(raw.editedText ?? raw.rawText ?? ''),
    speaker: String(raw.speaker ?? 'UNKNOWN') as TemporaryAsrSpeaker,
    speakerId: raw.speakerId == null ? null : String(raw.speakerId),
    speakerName: raw.speakerName == null ? null : String(raw.speakerName),
    speakerScore: nullableNumber(raw.speakerScore),
    secondBestScore: nullableNumber(raw.secondBestScore),
    speakerThreshold: nullableNumber(raw.speakerThreshold),
    speakerMargin: nullableNumber(raw.speakerMargin),
    speakerSource: String(raw.speakerSource ?? 'UNASSIGNED') as TemporaryAsrFragment['speakerSource'],
    voiceprintVerified: Boolean(raw.voiceprintVerified),
    confidence,
    confidenceSource: confidence == null ? 'UNAVAILABLE' : 'FUNASR',
    lowConfidence: Boolean(raw.lowConfidence),
    state: String(raw.state ?? 'PENDING') as TemporaryAsrFragment['state'],
    confirmedQaId: raw.confirmedMessageId == null ? null : String(raw.confirmedMessageId),
    confirmedMessageId: raw.confirmedMessageId == null ? null : String(raw.confirmedMessageId),
    modelId: raw.modelId == null ? null : String(raw.modelId),
    modelVersion: raw.modelVersion == null ? null : String(raw.modelVersion),
    recognitionEvidence: normalizeRecognitionEvidence(raw.recognitionEvidence),
    recognitionRevisions,
    lineage: Array.isArray(raw.lineage)
      ? raw.lineage.map((value) => {
        const item = asRecord(value)
        return {
          analysisJobId: String(item.analysisJobId ?? ''),
          parentFragmentId: String(item.parentFragmentId ?? ''),
          childFragmentId: String(item.childFragmentId ?? ''),
          relation: String(item.relation ?? ''),
        }
      })
      : [],
    // Task 17B-1: the mode the fragment was decided in survives normalization, so a
    // narrowed operating point is visible in the UI instead of being dropped here.
    ...modeFields(raw),
    audio: { captureSessionId, startOffsetMs: startedAtMs, endOffsetMs: endedAtMs, available: false },
    createdAt,
    updatedAt,
  }
}

async function loadNormalizedFragments(caseId: string, includeConfirmed = false, includeSuperseded = false): Promise<TemporaryAsrFragment[]> {
  const result = await runtime().invoke<unknown[]>('asr.fragment.list', { caseId, includeConfirmed, includeSuperseded })
  return Array.isArray(result) ? result.map(normalizeTemporaryAsrFragment) : []
}

async function normalizeCaptureStatus(caseId: string, value: unknown): Promise<AsrCaptureStatus> {
  const raw = asRecord(value)
  const normalizedCaseId = String(raw.caseId ?? caseId)
  const sourceValue = String(raw.source ?? '').toUpperCase()
  const fragments = Array.isArray(raw.fragments) ? raw.fragments.map(normalizeTemporaryAsrFragment) : await loadNormalizedFragments(normalizedCaseId)
  return {
    caseId: normalizedCaseId,
    captureSessionId: raw.captureSessionId == null ? null : String(raw.captureSessionId),
    source: sourceValue === 'BROWSER' || sourceValue === 'ALSA' ? sourceValue : null,
    running: Boolean(raw.running ?? raw.active),
    recordingStatus: raw.recordingStatus == null ? null : String(raw.recordingStatus),
    asrStatus: raw.asrStatus == null ? null : String(raw.asrStatus),
    speakerStatus: raw.speakerStatus == null ? null : String(raw.speakerStatus),
    audioSampleCount: nullableNumber(raw.audioSampleCount) ?? 0,
    asrCursorSample: nullableNumber(raw.asrCursorSample) ?? 0,
    voicedMs: nullableNumber(raw.voicedMs) ?? 0,
    finalFragmentCount: nullableNumber(raw.finalFragmentCount) ?? 0,
    startedAt: toTimestamp(raw.startedAt) ?? null,
    endedAt: toTimestamp(raw.endedAt) ?? null,
    sampleRate: Number(raw.sampleRate ?? 16_000),
    partialText: String(raw.partialText ?? ''),
    fragments,
    error: raw.error == null && raw.lastError == null ? null : String(raw.error ?? raw.lastError),
  }
}

export function backendErrorMessage(error: unknown): string {
  if (error instanceof RuntimeAdapterError) return error.message
  const axiosError = error as AxiosError<{ message?: string; code?: string }>
  const responseMessage = axiosError?.response?.data?.message
  if (responseMessage) return responseMessage
  if (axiosError?.code === 'ERR_NETWORK' || (error instanceof TypeError && /fetch/i.test(error.message))) return '无法连接 Linux 本地后端，请确认本机 FastAPI 服务已启动'
  if (error instanceof Error) return error.message
  return String(error)
}

export function fetchRuntimeCapabilities(force = false): Promise<RuntimeCapabilities> { return runtime().getCapabilities(force) }
export function connectRuntimeSession(sessionId: string, listener: RuntimeEventListener): RuntimeSessionConnection { return runtime().connectSession(sessionId, listener) }

export async function createCase(payload: Partial<CaseSummary> = {}): Promise<CaseSummary> {
  const request = { ...payload, operator_id: payload.officerName || '当前警官', case_type: 'suspect_interrogation' } as unknown as Record<string, unknown>
  return normalizeCaseSummary(await runtime().invoke<unknown>('case.create', request), payload)
}
export interface CaseIntakeInput {
  operatorId: string
  officerName: string
  caseType: string
  age?: string
  identity: {
    name: string
    gender?: string
    nation?: string
    birthDate?: string
    idNumber?: string
    address?: string
    source: string
  }
}
export async function createCaseWithIdentity(payload: CaseIntakeInput): Promise<CaseSummary> {
  const identity = payload.identity
  return normalizeCaseSummary(await runtime().invoke<unknown>('case.intake', { ...payload, case_type: payload.caseType }), {
    suspectName: identity.name,
    gender: identity.gender,
    nation: identity.nation,
    birthDate: identity.birthDate,
    idNumber: identity.idNumber,
    address: identity.address,
    identitySource: identity.source,
    officerName: payload.officerName,
  })
}
export async function fetchCases(limit = 50, query = ''): Promise<CaseSummary[]> {
  const result = await runtime().invoke<unknown[]>('case.list', { limit, query })
  return Array.isArray(result) ? result.map((item) => normalizeCaseSummary(item)) : []
}
export async function fetchCase(caseId: string): Promise<CaseSummary> { return normalizeCaseSummary(await runtime().invoke<unknown>('case.get', { caseId }), { id: caseId }) }
export function fetchMessages(caseId: string): Promise<TranscriptMessage[]> { return runtime().invoke<TranscriptMessage[]>('message.list', { caseId, limit: 1000 }) }
export function fetchFacts(caseId: string): Promise<FactItem[]> { return runtime().invoke<FactItem[]>('fact.list', { caseId }) }
export async function fetchSessionState(caseId: string): Promise<SessionState> { return normalizeSessionState(await runtime().invoke<unknown>('session.get', { caseId }), caseId) }
export function persistQuestionOrAnswer(caseId: string, text: string, speaker: '民警' | '嫌疑人'): Promise<TranscriptMessage> { return runtime().invoke<TranscriptMessage>('message.add', { caseId, text, speaker }) }
export function updateTranscriptMessage(caseId: string, messageId: string, text: string): Promise<TranscriptMessage> { return runtime().invoke<TranscriptMessage>('message.update', { caseId, messageId, text, reason: '警官在审讯工作台修订' }) }
export function markTranscriptMessage(caseId: string, messageId: string, mark: RecordMark): Promise<TranscriptMessage> { return runtime().invoke<TranscriptMessage>('message.mark', { caseId, messageId, mark }) }
export function fetchRevisions(caseId: string, messageId?: string): Promise<RecordRevision[]> { return runtime().invoke<RecordRevision[]>('message.revisions', { caseId, ...(messageId ? { messageId } : {}) }) }

async function sessionAction(caseId: string, action: 'pause' | 'resume' | 'finish'): Promise<SessionState> {
  return normalizeSessionState(await runtime().invoke<unknown>(`session.${action}`, { caseId }), caseId)
}
export async function startSession(
  caseId: string,
  interrogatorOfficerId?: string | null,
  recorderOfficerId?: string | null,
  actorId?: string,
): Promise<SessionState> {
  return normalizeSessionState(await runtime().invoke<unknown>('session.start', {
    caseId,
    interrogatorOfficerId: interrogatorOfficerId ?? null,
    recorderOfficerId: recorderOfficerId ?? null,
    actorId,
  }), caseId)
}
export const pauseSession = (caseId: string) => sessionAction(caseId, 'pause')
export const resumeSession = (caseId: string) => sessionAction(caseId, 'resume')
export const finishSession = (caseId: string) => sessionAction(caseId, 'finish')
export async function changeSessionStage(caseId: string, stage: InterrogationStage): Promise<SessionState> { return normalizeSessionState(await runtime().invoke<unknown>('session.stage', { caseId, stage }), caseId) }
export function invokeDeviceAction(type: 'identity' | 'fingerprint' | 'signature'): Promise<DeviceActionResult> { return runtime().invoke<DeviceActionResult>('device.action', { type }) }

export async function fetchVoiceprintReadiness(caseId: string): Promise<VoiceprintReadiness> { return normalizeVoiceprintReadiness(await runtime().invoke<unknown>('voiceprint.readiness', { caseId })) }
export async function fetchVoiceprintRoleDraft(caseId: string): Promise<VoiceprintRoleDraft> {
  return normalizeVoiceprintRoleDraft(await runtime().invoke<unknown>('voiceprint.roleDraft.get', { caseId }))
}
export async function fetchVoiceprintEnrollmentStatus(): Promise<VoiceprintCaptureStatus> { return normalizeVoiceprintCaptureStatus(await runtime().invoke<unknown>('voiceprint.enrollment.status', {})) }
export function startSuspectVoiceprintEnrollment(caseId: string, actorId?: string): Promise<VoiceprintEnrollmentResult> { return runtime().invoke<VoiceprintEnrollmentResult>('voiceprint.suspect.enrollment.start', { caseId, actorId }) }
export function stopSuspectVoiceprintEnrollment(caseId: string, actorId?: string): Promise<VoiceprintEnrollmentResult> { return runtime().invoke<VoiceprintEnrollmentResult>('voiceprint.suspect.enrollment.stop', { caseId, actorId }, { timeoutMs: 120_000 }) }
export async function fetchOfficerVoiceprints(activeOnly = true): Promise<OfficerVoiceprint[]> {
  const result = await runtime().invoke<unknown[]>('officerVoiceprint.list', { activeOnly })
  return Array.isArray(result) ? result.map(normalizeOfficerVoiceprint) : []
}
export function startOfficerVoiceprintEnrollment(officerId: string, officerName: string, actorId?: string): Promise<VoiceprintEnrollmentResult> { return runtime().invoke<VoiceprintEnrollmentResult>('officerVoiceprint.enrollment.start', { officerId, officerName, actorId }) }
export function stopOfficerVoiceprintEnrollment(officerId: string, actorId?: string): Promise<VoiceprintEnrollmentResult> { return runtime().invoke<VoiceprintEnrollmentResult>('officerVoiceprint.enrollment.stop', { officerId, actorId }, { timeoutMs: 120_000 }) }
export async function revokeOfficerVoiceprint(officerId: string, actorId?: string): Promise<OfficerVoiceprint> { return normalizeOfficerVoiceprint(await runtime().invoke<unknown>('officerVoiceprint.revoke', { officerId, actorId })) }
export async function updateVoiceprintAssignments(caseId: string, interrogatorOfficerId?: string | null, recorderOfficerId?: string | null, actorId?: string): Promise<VoiceprintReadiness> {
  return normalizeVoiceprintReadiness(await runtime().invoke<unknown>('voiceprint.assignments.update', { caseId, interrogatorOfficerId: interrogatorOfficerId ?? null, recorderOfficerId: recorderOfficerId ?? null, actorId }))
}
export async function updateVoiceprintRoleDraft(caseId: string, interrogatorOfficerId?: string | null, recorderOfficerId?: string | null, actorId?: string): Promise<VoiceprintRoleDraft> {
  return normalizeVoiceprintRoleDraft(await runtime().invoke<unknown>('voiceprint.roleDraft.update', {
    caseId,
    interrogatorOfficerId: interrogatorOfficerId ?? null,
    recorderOfficerId: recorderOfficerId ?? null,
    actorId,
  }))
}

export async function fetchAsrCaptureStatus(caseId: string): Promise<AsrCaptureStatus> { return normalizeCaptureStatus(caseId, await runtime().invoke<unknown>('asr.capture.status', { caseId })) }
export async function startAsrCapture(caseId: string): Promise<AsrCaptureStatus> { return normalizeCaptureStatus(caseId, await runtime().invoke<unknown>('asr.capture.start', { caseId }, { timeoutMs: 120_000 })) }
export async function stopAsrCapture(caseId: string): Promise<AsrCaptureStatus> { return normalizeCaptureStatus(caseId, await runtime().invoke<unknown>('asr.capture.stop', { caseId }, { timeoutMs: 30_000 })) }
export function listAsrFragments(caseId: string, includeConfirmed = false, includeSuperseded = false): Promise<TemporaryAsrFragment[]> { return loadNormalizedFragments(caseId, includeConfirmed, includeSuperseded) }
export async function updateAsrFragment(
  caseId: string,
  fragmentId: string,
  editedText: string,
  speaker: TemporaryAsrSpeaker,
  actorId?: string,
  reason?: string,
): Promise<TemporaryAsrFragment> {
  return normalizeTemporaryAsrFragment(await runtime().invoke<unknown>('asr.fragment.update', { caseId, fragmentId, editedText, speaker, actorId, reason }))
}
export async function confirmAsrFragment(caseId: string, fragmentId: string): Promise<TemporaryAsrFragment> { return normalizeTemporaryAsrFragment(await runtime().invoke<unknown>('asr.fragment.confirm', { caseId, fragmentId })) }
export async function confirmAsrFragmentBatch(caseId: string, fragmentIds: string[]): Promise<{ confirmedCount: number; fragments: TemporaryAsrFragment[] }> {
  const raw = asRecord(await runtime().invoke<unknown>('asr.fragment.confirmBatch', { caseId, fragmentIds }))
  const fragments = Array.isArray(raw.fragments) ? raw.fragments.map(normalizeTemporaryAsrFragment) : []
  return { confirmedCount: Number(raw.confirmedCount ?? fragments.length), fragments }
}
export async function applyAsrFragmentsToRecord(caseId: string, _captureSessionId: string, _recordId: string, fragmentIds: string[], _text: string): Promise<{ confirmedCount: number; fragments: TemporaryAsrFragment[] }> {
  const raw = asRecord(await runtime().invoke<unknown>('asr.fragment.applyToRecord', { caseId, fragmentIds }))
  const fragments = Array.isArray(raw.fragments) ? raw.fragments.map(normalizeTemporaryAsrFragment) : []
  return { confirmedCount: Number(raw.confirmedCount ?? fragments.length), fragments }
}
export async function discardAsrFragment(caseId: string, fragmentId: string): Promise<TemporaryAsrFragment> { return normalizeTemporaryAsrFragment(await runtime().invoke<unknown>('asr.fragment.discard', { caseId, fragmentId })) }
