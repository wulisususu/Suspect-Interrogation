import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  backendErrorMessage,
  changeSessionStage,
  connectRuntimeSession,
  confirmAsrFragment,
  confirmAsrFragmentBatch,
  discardAsrFragment,
  fetchAsrCaptureStatus,
  fetchCase,
  fetchFacts,
  fetchMessages,
  fetchOfficerVoiceprints,
  fetchRevisions,
  fetchRuntimeCapabilities,
  fetchSessionState,
  fetchVoiceprintEnrollmentStatus,
  fetchVoiceprintReadiness,
  fetchVoiceprintRoleDraft,
  finishSession as finishSessionApi,
  markTranscriptMessage,
  normalizeTemporaryAsrFragment,
  pauseSession as pauseSessionApi,
  persistQuestionOrAnswer,
  resumeSession as resumeSessionApi,
  revokeOfficerVoiceprint as revokeOfficerVoiceprintApi,
  startAsrCapture,
  startOfficerVoiceprintEnrollment as startOfficerVoiceprintEnrollmentApi,
  startSession as startSessionApi,
  startSuspectVoiceprintEnrollment as startSuspectVoiceprintEnrollmentApi,
  stopAsrCapture,
  stopOfficerVoiceprintEnrollment as stopOfficerVoiceprintEnrollmentApi,
  stopSuspectVoiceprintEnrollment as stopSuspectVoiceprintEnrollmentApi,
  updateAsrFragment,
  updateTranscriptMessage,
  updateVoiceprintAssignments,
  updateVoiceprintRoleDraft,
} from '../api/interrogation'
import { resetCurrentOperator, setCurrentOperator } from '../api/operator'
import {
  clearBrowserAsrCaptureLeaseRefusal,
  BrowserFormalCaptureLeaseError,
  setBrowserAsrIncompleteCaptureListener,
  setBrowserAsrUnexpectedCloseListener,
  startBrowserAsrCapture,
} from '../audio/browserAsrCapture'
import { BrowserCaptureResumeGate } from '../audio/browserCaptureResumeGate'
import { audioInputMode } from '../config/audioInput'
import {
  removeReplacedAsrFragmentSelection,
  replaceAsrFragmentGroup,
  upsertAsrFragmentByCaptureTime,
} from '../utils/asrFragments'
import type { RuntimeSessionConnection } from '../runtime'
import type {
  AudioLevelSample,
  AsrCaptureStatus,
  AsrInsertionReceipt,
  AsrInsertionTarget,
  CaseSummary,
  FactItem,
  InterrogationStage,
  OfficerVoiceprint,
  RecordRevision,
  SessionState,
  TemporaryAsrFragment,
  TemporaryAsrSpeaker,
  TranscriptMessage,
  VoiceprintEnrollmentState,
  VoiceprintReadiness,
} from '../types/interrogation'

const uid = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`
const stageOrder: InterrogationStage[] = ['IDENTITY', 'STATEMENT', 'FOLLOW_UP', 'SIGNING']

const workflowStateTextMap: Record<string, string> = {
  INIT: '草稿',
  IDENTITY_REQUIRED: '待核验身份',
  IDENTITY_READY: '身份已核验',
  CASE_CREATED: '待开始审讯',
  QUESTIONING: '审讯中',
  PAUSED: '已暂停',
  SUMMARY: '待定稿',
  FROZEN: '已冻结',
  SIGNED: '已签署',
  REPORT_GENERATED: '已归档',
}

const stageTextMap: Record<InterrogationStage, string> = {
  IDENTITY: '身份核验',
  STATEMENT: '案情陈述',
  FOLLOW_UP: '重点追问',
  SIGNING: '确认签名',
}

interface CaseScope {
  caseId: string
  generation: number
}

interface CaptureEvent {
  event: string
  payload: unknown
}

function emptyCaseSummary(caseId = ''): CaseSummary {
  return {
    id: caseId,
    suspectName: '',
    gender: '',
    age: '',
    officerName: '',
    state: 'DRAFT',
    stage: 'IDENTITY',
  }
}

function emptySession(caseId = ''): SessionState {
  return {
    id: null,
    caseId,
    status: 'READY',
    stage: 'IDENTITY',
    startedAt: null,
    pausedAt: null,
    endedAt: null,
    updatedAt: Date.now(),
  }
}

function emptyCapture(caseId = ''): AsrCaptureStatus {
  return {
    caseId,
    captureSessionId: null,
    running: false,
    startedAt: null,
    endedAt: null,
    sampleRate: 16_000,
    audioLevels: [],
    audioLevelUpdatedAt: null,
    partialText: '',
    partialStartedAtMs: null,
    partialEndedAtMs: null,
    liveTranscriptStatus: 'UNKNOWN',
    fragments: [],
    error: null,
  }
}

function emptyVoiceprintReadiness(): VoiceprintReadiness {
  return {
    suspectReady: false,
    interrogatorReady: false,
    recorderReady: false,
    recognitionMode: 'SUSPECT_ONLY',
    canStart: false,
    roleBindingScope: 'NONE',
    roleBindingSessionId: null,
  }
}

function idleEnrollmentState(): VoiceprintEnrollmentState {
  return { phase: 'IDLE', kind: null, subjectId: null, officerName: null, usableDurationMs: null, message: null }
}

export const useInterrogationStore = defineStore('interrogation', () => {
  const params = new URLSearchParams(location.search)
  const caseId = ref(params.get('caseId') || '')
  const loading = ref(true)
  const streaming = ref(false)
  const error = ref('')
  const actionMessage = ref('')
  const actionError = ref('')
  const revisions = ref<RecordRevision[]>([])
  const revisionsOpen = ref(false)
  const captureAvailable = ref(false)
  const captureBusy = ref(false)
  const captureInsertionReceipt = ref<AsrInsertionReceipt | null>(null)
  const captureClock = ref(Date.now())
  const selectedFragmentIds = ref<string[]>([])
  const capture = ref<AsrCaptureStatus>(emptyCapture(caseId.value))
  const archivedFragments = ref<Record<string, TemporaryAsrFragment>>({})
  const lineageGroups = ref<Record<string, string[]>>({})
  const lineageGroupByFragment = ref<Record<string, string>>({})
  const processedReplacementJobIds = new Set<string>()
  const formalRecordRevision = ref(0)
  const caseSummary = ref<CaseSummary>(emptyCaseSummary(caseId.value))
  const session = ref<SessionState>(emptySession(caseId.value))
  const transcript = ref<TranscriptMessage[]>([])
  const facts = ref<FactItem[]>([])
  const voiceprintReadiness = ref<VoiceprintReadiness>(emptyVoiceprintReadiness())
  const officerVoiceprints = ref<OfficerVoiceprint[]>([])
  const selectedInterrogatorOfficerId = ref<string | null>(null)
  const selectedRecorderOfficerId = ref<string | null>(null)
  const voiceprintEnrollmentState = ref<VoiceprintEnrollmentState>(idleEnrollmentState())
  const voiceprintBusy = ref(false)

  let caseGeneration = 0
  let feedbackTimer: ReturnType<typeof setTimeout> | undefined
  let captureTimer: ReturnType<typeof setInterval> | undefined
  let captureStatusSyncTimer: ReturnType<typeof setInterval> | undefined
  let captureStatusSyncInFlight = false
  const browserResumeGate = new BrowserCaptureResumeGate()
  let voiceprintProgressTimer: ReturnType<typeof setInterval> | undefined
  let sessionConnection: RuntimeSessionConnection | undefined
  /** 本连接生命周期内收到过的 STATE_SYNC 次数；第一次是建连快照，之后才是重连补账。 */
  let stateSyncCount = 0

  const completion = computed(() => {
    if (!facts.value.length) return 0
    const done = facts.value.filter((item) => item.status === 'confirmed').length
    return Math.round((done / facts.value.length) * 100)
  })
  // 状态文案只认工作流状态：兼容字段 state 对已归档案件也返回 REVIEWING。
  const stateText = computed(() => {
    const workflow = caseSummary.value.workflowState
    if (workflow) return workflowStateTextMap[workflow] ?? workflow
    return ''
  })
  const stageText = computed(() => stageTextMap[session.value.stage])
  const canRecord = computed(() => session.value.status === 'RUNNING')
  const captureElapsedMs = computed(() => capture.value.running && capture.value.startedAt
    ? Math.max(0, captureClock.value - capture.value.startedAt)
    : 0)
  const activeFragments = computed(() => capture.value.fragments.filter((fragment) => fragment.state !== 'SUPERSEDED'))

  function captureWorkflowNeedsSync(status = capture.value) {
    const hasPendingSpeakerAnalysis = status.fragments.some((fragment) =>
      fragment.state !== 'SUPERSEDED'
      && (fragment.speaker === 'UNKNOWN' || fragment.speakerSource === 'PENDING_ANALYSIS'),
    )
    return status.running
      || status.recordingStatus === 'CAPTURING'
      || status.asrStatus === 'PENDING'
      || status.asrStatus === 'FINALIZING'
      || status.speakerStatus === 'QUEUED'
      || status.speakerStatus === 'RUNNING'
      || (status.speakerStatus === 'PENDING'
        && status.asrStatus === 'COMPLETE'
        && hasPendingSpeakerAnalysis)
  }

  function currentScope(): CaseScope {
    return { caseId: caseId.value, generation: caseGeneration }
  }

  function isCurrentScope(scope: CaseScope) {
    return scope.generation === caseGeneration && scope.caseId === caseId.value
  }

  function appendAudioLevel(sample: AudioLevelSample, scope: CaseScope, captureSessionId: string) {
    if (!isCurrentScope(scope) || !capture.value.running
      || capture.value.captureSessionId !== captureSessionId) return
    capture.value.audioLevels = [...(capture.value.audioLevels ?? []), sample].slice(-240)
    capture.value.audioLevelUpdatedAt = Date.now()
  }

  function disposeCaptureEvents() {
    sessionConnection?.close()
    sessionConnection = undefined
    stateSyncCount = 0
    if (captureTimer) clearInterval(captureTimer)
    captureTimer = undefined
    if (captureStatusSyncTimer) clearInterval(captureStatusSyncTimer)
    captureStatusSyncTimer = undefined
    captureStatusSyncInFlight = false
  }

  function resetCaseContext(nextCaseId = '') {
    caseGeneration += 1
    stopVoiceprintProgressPolling()
    disposeCaptureEvents()
    if (feedbackTimer) clearTimeout(feedbackTimer)
    feedbackTimer = undefined

    caseId.value = nextCaseId
    loading.value = true
    streaming.value = false
    error.value = ''
    actionMessage.value = ''
    actionError.value = ''
    revisions.value = []
    revisionsOpen.value = false
    captureAvailable.value = false
    captureBusy.value = false
    captureInsertionReceipt.value = null
    captureClock.value = Date.now()
    selectedFragmentIds.value = []
    capture.value = emptyCapture(nextCaseId)
    archivedFragments.value = {}
    lineageGroups.value = {}
    lineageGroupByFragment.value = {}
    processedReplacementJobIds.clear()
    formalRecordRevision.value = 0
    caseSummary.value = emptyCaseSummary(nextCaseId)
    session.value = emptySession(nextCaseId)
    transcript.value = []
    facts.value = []
    voiceprintReadiness.value = emptyVoiceprintReadiness()
    officerVoiceprints.value = []
    selectedInterrogatorOfficerId.value = null
    selectedRecorderOfficerId.value = null
    resetCurrentOperator()
    voiceprintEnrollmentState.value = idleEnrollmentState()
    voiceprintBusy.value = false
  }

  function feedback(message: string, isError = false) {
    if (feedbackTimer) clearTimeout(feedbackTimer)
    if (isError) {
      actionError.value = message
      actionMessage.value = ''
    } else {
      actionMessage.value = message
      actionError.value = ''
    }
    feedbackTimer = setTimeout(() => {
      actionMessage.value = ''
      actionError.value = ''
    }, isError ? 5000 : 3000)
  }

  function feedbackIfCurrent(scope: CaseScope, message: string, isError = false) {
    if (isCurrentScope(scope)) feedback(message, isError)
  }

  function applyCaptureStatus(status: AsrCaptureStatus, scope = currentScope()) {
    if (!isCurrentScope(scope) || status.caseId !== scope.caseId) return
    const sameCapture = Boolean(status.captureSessionId && status.captureSessionId === capture.value.captureSessionId)
    const audioLevels = sameCapture ? capture.value.audioLevels ?? [] : []
    const audioLevelUpdatedAt = sameCapture ? capture.value.audioLevelUpdatedAt ?? null : null
    const partialText = sameCapture ? capture.value.partialText : status.partialText ?? ''
    const partialStartedAtMs = sameCapture
      ? capture.value.partialStartedAtMs ?? null
      : status.partialStartedAtMs ?? null
    const partialEndedAtMs = sameCapture
      ? capture.value.partialEndedAtMs ?? null
      : status.partialEndedAtMs ?? null
    const liveTranscriptStatus = status.liveTranscriptStatus
      ?? (sameCapture ? capture.value.liveTranscriptStatus : 'UNKNOWN')
    for (const fragment of status.fragments) rememberFragment(fragment)
    capture.value = {
      ...status,
      audioLevels,
      audioLevelUpdatedAt,
      partialText,
      partialStartedAtMs,
      partialEndedAtMs,
      liveTranscriptStatus,
      fragments: status.fragments.filter((fragment) => fragment.state !== 'SUPERSEDED'),
    }
    if (!status.running) {
      browserResumeGate.reset()
      clearBrowserAsrCaptureLeaseRefusal(status.caseId, status.captureSessionId)
    } else if (
      audioInputMode === 'BROWSER'
      && status.source === 'BROWSER'
      && status.captureSessionId
    ) {
      const captureKey = `${status.caseId}:${status.captureSessionId}`
      if (browserResumeGate.shouldAttempt(captureKey)) {
        browserResumeGate.markAttempted(captureKey)
        void startBrowserAsrCapture(status.caseId, status.captureSessionId, undefined, (sample) => {
          appendAudioLevel(sample, scope, status.captureSessionId!)
        }).catch((err) => {
          if (err instanceof BrowserFormalCaptureLeaseError && err.reason === 'CONFLICT') {
            if (browserResumeGate.leaseConflict(captureKey)) {
              feedbackIfCurrent(scope, '此录音正在另一个标签页中采集；将等待该标签页释放录音后自动恢复', true)
            }
            return
          }
          feedbackIfCurrent(scope, `恢复浏览器录音失败：${backendErrorMessage(err)}`, true)
        })
      }
    }
    const visibleIds = new Set(status.fragments.map((fragment) => fragment.id))
    selectedFragmentIds.value = selectedFragmentIds.value.filter((id) => visibleIds.has(id))
    if (status.running && !captureTimer) {
      captureTimer = setInterval(() => { captureClock.value = Date.now() }, 500)
    } else if (!status.running && captureTimer) {
      clearInterval(captureTimer)
      captureTimer = undefined
    }
    if (captureWorkflowNeedsSync(status) && !captureStatusSyncTimer) startCaptureStatusSync(scope)
    else if (!captureWorkflowNeedsSync(status)) stopCaptureStatusSync()
  }

  function stopCaptureStatusSync() {
    if (captureStatusSyncTimer) clearInterval(captureStatusSyncTimer)
    captureStatusSyncTimer = undefined
    captureStatusSyncInFlight = false
  }

  async function pullCaptureStatus(scope: CaseScope) {
    if (captureStatusSyncInFlight || !isCurrentScope(scope)) return
    captureStatusSyncInFlight = true
    try {
      const status = await fetchAsrCaptureStatus(scope.caseId)
      applyCaptureStatus(status, scope)
    } catch {
      // The WebSocket remains the primary live path. Polling only repairs a
      // missed event, so a transient status request must not interrupt capture.
    } finally {
      captureStatusSyncInFlight = false
    }
  }

  async function syncCaptureStatus(scope: CaseScope) {
    if (!captureWorkflowNeedsSync()) return
    await pullCaptureStatus(scope)
  }

  function startCaptureStatusSync(scope: CaseScope) {
    captureStatusSyncTimer = setInterval(() => {
      void syncCaptureStatus(scope)
    }, 2000)
  }

  function upsertAsrFragment(fragment: TemporaryAsrFragment, scope = currentScope()) {
    if (!isCurrentScope(scope) || fragment.caseId !== scope.caseId) return
    rememberFragment(fragment)
    if (fragment.state !== 'SUPERSEDED') {
      capture.value.fragments = upsertAsrFragmentByCaptureTime(capture.value.fragments, fragment)
    }
    if (!capture.value.captureSessionId) capture.value.captureSessionId = fragment.captureSessionId
  }

  function rememberFragment(fragment: TemporaryAsrFragment) {
    archivedFragments.value[fragment.id] = fragment
  }

  function connectLineage(parentFragmentId: string, childFragmentId: string) {
    const parentRoot = lineageGroupByFragment.value[parentFragmentId] ?? parentFragmentId
    const childRoot = lineageGroupByFragment.value[childFragmentId] ?? childFragmentId
    const members = new Set([
      parentFragmentId,
      childFragmentId,
      ...(lineageGroups.value[parentRoot] ?? []),
      ...(lineageGroups.value[childRoot] ?? []),
    ])
    const root = parentRoot
    for (const previousRoot of new Set([parentRoot, childRoot])) {
      if (previousRoot !== root) delete lineageGroups.value[previousRoot]
    }
    lineageGroups.value[root] = [...members]
    for (const id of members) lineageGroupByFragment.value[id] = root
  }

  function hydrateFragmentHistory(fragments: TemporaryAsrFragment[], scope = currentScope()) {
    if (!isCurrentScope(scope)) return
    archivedFragments.value = {}
    lineageGroups.value = {}
    lineageGroupByFragment.value = {}
    processedReplacementJobIds.clear()
    for (const fragment of fragments) rememberFragment(fragment)
    for (const fragment of fragments) {
      for (const relation of fragment.lineage ?? []) {
        if (relation.parentFragmentId && relation.childFragmentId) {
          connectLineage(relation.parentFragmentId, relation.childFragmentId)
        }
      }
    }
  }

  function fragmentHistory(fragmentId: string) {
    const root = lineageGroupByFragment.value[fragmentId]
    const ids = root ? lineageGroups.value[root] ?? [] : [fragmentId]
    return ids
      .map((id) => archivedFragments.value[id])
      .filter((fragment): fragment is TemporaryAsrFragment => Boolean(fragment))
      .sort((left, right) => left.startedAtMs - right.startedAtMs || left.ordinal - right.ordinal || left.id.localeCompare(right.id))
  }

  function applyCaptureEvent(event: CaptureEvent, scope = currentScope()) {
    if (!isCurrentScope(scope)) return
    if (event.event === 'AUDIO_LEVEL') {
      if (capture.value.source === 'BROWSER') return
      const payload = event.payload as Partial<AudioLevelSample> & { caseId?: string; captureSessionId?: string }
      if (payload.caseId !== scope.caseId || !payload.captureSessionId
        || payload.captureSessionId !== capture.value.captureSessionId
        || !Number.isFinite(payload.sampleCount) || !Number.isFinite(payload.sampleRate)
        || !Number.isFinite(payload.rms) || !Number.isFinite(payload.peak)) return
      const sample: AudioLevelSample = {
        sampleCount: payload.sampleCount!,
        sampleRate: payload.sampleRate!,
        rms: payload.rms!,
        peak: payload.peak!,
      }
      appendAudioLevel(sample, scope, payload.captureSessionId)
      return
    }
    if (event.event === 'ASR_PARTIAL') {
      const payload = event.payload as {
        caseId?: string
        captureSessionId?: string
        text?: string
        partialText?: string
        startedAtMs?: number
        endedAtMs?: number
      }
      if (payload.caseId && payload.caseId !== scope.caseId) return
      if (payload.captureSessionId && payload.captureSessionId !== capture.value.captureSessionId) return
      const text = String(payload.partialText ?? payload.text ?? '').trim()
      if (!text) return
      if (Number.isFinite(payload.startedAtMs) && Number.isFinite(payload.endedAtMs)) {
        const startedAtMs = Number(payload.startedAtMs)
        if (capture.value.partialStartedAtMs !== null
          && capture.value.partialStartedAtMs !== undefined
          && startedAtMs < capture.value.partialStartedAtMs) return
        capture.value.partialStartedAtMs = startedAtMs
        capture.value.partialEndedAtMs = Number(payload.endedAtMs)
      }
      capture.value.partialText = text
      return
    }
    if (event.event === 'ASR_FINAL') {
      const payload = event.payload as { captureSessionId?: string; text?: string; startedAtMs?: number; endedAtMs?: number }
      if (payload.captureSessionId && payload.captureSessionId !== capture.value.captureSessionId) return
      if (payload.text?.trim()) {
        capture.value.partialText = payload.text
        capture.value.partialStartedAtMs = Number.isFinite(payload.startedAtMs) ? Number(payload.startedAtMs) : null
        capture.value.partialEndedAtMs = Number.isFinite(payload.endedAtMs) ? Number(payload.endedAtMs) : null
      }
      return
    }
    if (event.event === 'ASR_FRAGMENT') {
      const fragment = normalizeTemporaryAsrFragment(event.payload)
      if (capture.value.partialStartedAtMs === fragment.startedAtMs) {
        capture.value.partialText = ''
        capture.value.partialStartedAtMs = null
        capture.value.partialEndedAtMs = null
      }
      upsertAsrFragment(fragment, scope)
      return
    }
    if (event.event === 'ASR_PREVIEW_STATUS') {
      const payload = event.payload as {
        caseId?: string
        captureSessionId?: string
        status?: AsrCaptureStatus['liveTranscriptStatus']
      }
      if (payload.caseId && payload.caseId !== scope.caseId) return
      if (payload.captureSessionId && payload.captureSessionId !== capture.value.captureSessionId) return
      capture.value.liveTranscriptStatus = payload.status ?? 'ERROR'
      return
    }
    if (event.event === 'ASR_FRAGMENT_REPLACED') {
      const payload = event.payload as { parentFragmentId?: string; fragments?: unknown[]; jobId?: string }
      const parentFragmentId = payload.parentFragmentId
      const children = Array.isArray(payload.fragments)
        ? payload.fragments.map(normalizeTemporaryAsrFragment)
        : []
      if (!parentFragmentId || children.some((fragment) => fragment.caseId !== scope.caseId)) return
      if (payload.jobId && processedReplacementJobIds.has(payload.jobId)) return
      const parent = archivedFragments.value[parentFragmentId]
        ?? capture.value.fragments.find((fragment) => fragment.id === parentFragmentId)
      if (parent) rememberFragment({ ...parent, state: 'SUPERSEDED' })
      for (const child of children) {
        const lineage = [
          ...(child.lineage ?? []),
          ...(child.lineage ?? []).some((item) => item.parentFragmentId === parentFragmentId && item.childFragmentId === child.id)
            ? []
            : [{
              analysisJobId: payload.jobId ?? '',
              parentFragmentId,
              childFragmentId: child.id,
              relation: 'SUPERSEDES',
            }],
        ]
        rememberFragment({ ...child, lineage })
        connectLineage(parentFragmentId, child.id)
      }
      capture.value.fragments = replaceAsrFragmentGroup(
        capture.value.fragments,
        parentFragmentId,
        children,
      ).filter((fragment) => fragment.state !== 'SUPERSEDED')
      selectedFragmentIds.value = removeReplacedAsrFragmentSelection(
        selectedFragmentIds.value,
        parentFragmentId,
      )
      if (!capture.value.captureSessionId && children[0]) capture.value.captureSessionId = children[0].captureSessionId
      if (payload.jobId) processedReplacementJobIds.add(payload.jobId)
      return
    }
    if (event.event === 'RECORDING_STATE') {
      const payload = event.payload as Partial<AsrCaptureStatus> & {
        caseId?: string
        captureSessionId?: string | null
        running?: boolean
        active?: boolean
      }
      if (payload.caseId && payload.caseId !== scope.caseId) return
      // 后端推送的是轻量信号（只有 running / captureSessionId），片段与计数字段
      // 仍由 REST 归一化产出；直接套用会把本地已有片段列表清空。
      if (!Array.isArray(payload.fragments) && (payload.running !== undefined || payload.active !== undefined)) {
        const nextRunning = Boolean(payload.running ?? payload.active)
        // 这里不能走 captureWorkflowNeedsSync 门禁：本机没在录音时它恒为 false，
        // 别的终端一开录就永远拉不到状态。推送本身就是"该刷新了"的信号。
        if (nextRunning !== capture.value.running) void pullCaptureStatus(scope)
        return
      }
    }
    if (event.event === 'RECORDING_STATE' || event.event === 'asr.capture.status') {
      const status = event.payload as Partial<AsrCaptureStatus>
      if (status.caseId === scope.caseId && typeof status.running === 'boolean' && Array.isArray(status.fragments)) {
        applyCaptureStatus(status as AsrCaptureStatus, scope)
      }
    }
  }

  /**
   * 处理后端 STATE_SYNC 快照（连接建立时与重连请求后各发一次）。
   *
   * 快照里的 messages 是后端原始序列化结果，前端各处消费者都依赖归一化后的
   * 形态，因此这里不直接灌入列表，而是把它当成"这段时间可能漏了事件"的信号，
   * 用已有的 REST 归一化链路重新取权威数据。
   */
  function applyStateSync(payload: unknown, scope: CaseScope) {
    const raw = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {}
    const syncCaseId = String(raw.case_id ?? raw.caseId ?? '')
    if (syncCaseId && syncCaseId !== scope.caseId) return
    const nextSession = raw.session
    if (nextSession && typeof nextSession === 'object') {
      const next = nextSession as Partial<SessionState>
      session.value = {
        ...session.value,
        ...next,
        caseId: scope.caseId,
        updatedAt: next.updatedAt ?? Date.now(),
      }
    }
    stateSyncCount += 1
    // 建连时的第一份快照与 initialize() 的 REST 拉取重复，不再重复请求；
    // 第二次起才说明是断线重连，需要把断连窗口里丢掉的事件补齐。
    if (stateSyncCount === 1) return
    formalRecordRevision.value += 1
    void refreshTranscript(scope).catch(() => undefined)
    void refreshCase(scope).catch(() => undefined)
    void pullCaptureStatus(scope)
  }

  function initializeRuntimeEvents(scope: CaseScope) {
    if (sessionConnection || !scope.caseId || !session.value.id) return
    sessionConnection = connectRuntimeSession(session.value.id, (event) => {
      if (!isCurrentScope(scope)) return
      if (event.event === 'STATE_SYNC') {
        applyStateSync(event.payload, scope)
        return
      }
      if (event.event === 'QA_UNIT_UPDATED' || event.event === 'FORMAL_RECORD_UPDATED') {
        formalRecordRevision.value += 1
        return
      }
      if (event.event === 'ASR_PARTIAL' || event.event === 'ASR_FINAL'
        || event.event === 'ASR_PREVIEW_STATUS'
        || event.event === 'ASR_FRAGMENT' || event.event === 'ASR_FRAGMENT_REPLACED'
        || event.event === 'AUDIO_LEVEL'
        || event.event === 'RECORDING_STATE' || event.event === 'asr.capture.status') {
        applyCaptureEvent(event, scope)
        return
      }
      if (event.event === 'SESSION_STATE') {
        applySessionState(event.payload, scope)
      }
    })
  }

  /** 应用后端推送的会话状态（SESSION_STATE）。 */
  function applySessionState(payload: unknown, scope: CaseScope) {
    const next = (payload && typeof payload === 'object' ? payload : {}) as Partial<SessionState>
    if (next.caseId && next.caseId !== scope.caseId) return
    const statusChanged = next.status !== undefined && next.status !== session.value.status
    session.value = {
      ...session.value,
      ...next,
      caseId: scope.caseId,
      updatedAt: next.updatedAt ?? Date.now(),
    }
    // 别的终端暂停/结束时，本机的步骤条与按钮门禁由案件 workflowState 派生，
    // 只改 session 不会让页面跟着走，所以再取一次案件摘要。
    if (statusChanged) void refreshCase(scope).catch(() => undefined)
  }

  async function initialize() {
    const generation = caseGeneration
    const requestedCaseId = caseId.value
    loading.value = true
    error.value = ''

    if (!requestedCaseId) {
      loading.value = false
      error.value = '请先建案后进入审讯工作台'
      return
    }

    try {
      const summary = await fetchCase(requestedCaseId)

      const scope: CaseScope = { caseId: requestedCaseId, generation }
      if (!isCurrentScope(scope) || summary.id !== requestedCaseId) return

      const runtimeCapabilities = await fetchRuntimeCapabilities()
      captureAvailable.value = runtimeCapabilities.recording.state === 'AVAILABLE' || runtimeCapabilities.asr.state === 'AVAILABLE'
      const [messages, factItems, sessionState, captureStatus, readiness, officers, roleDraft] = await Promise.all([
        fetchMessages(requestedCaseId),
        fetchFacts(requestedCaseId),
        fetchSessionState(requestedCaseId),
        captureAvailable.value ? fetchAsrCaptureStatus(requestedCaseId) : Promise.resolve(null),
        fetchVoiceprintReadiness(requestedCaseId),
        fetchOfficerVoiceprints(true),
        fetchVoiceprintRoleDraft(requestedCaseId),
      ])

      if (!isCurrentScope(scope)) return
      if (sessionState.caseId !== requestedCaseId) throw new Error('会话状态案件号与当前案件不一致')
      if (captureStatus && captureStatus.caseId !== requestedCaseId) throw new Error('录音状态案件号与当前案件不一致')

      caseSummary.value = summary
      transcript.value = messages
      facts.value = factItems
      session.value = sessionState
      voiceprintReadiness.value = readiness
      officerVoiceprints.value = officers
      selectedInterrogatorOfficerId.value = roleDraft.interrogatorOfficerId
      selectedRecorderOfficerId.value = roleDraft.recorderOfficerId
      setCurrentOperator(roleDraft.interrogatorOfficerId)
      initializeRuntimeEvents(scope)
      if (captureStatus) applyCaptureStatus(captureStatus, scope)
    } catch (err) {
      const scope: CaseScope = { caseId: requestedCaseId, generation }
      if (!isCurrentScope(scope)) return
      error.value = backendErrorMessage(err)
      feedback(`后端初始化失败：${error.value}`, true)
    } finally {
      const scope: CaseScope = { caseId: requestedCaseId, generation }
      if (isCurrentScope(scope)) loading.value = false
    }
  }

  async function refreshTranscript(scope = currentScope()) {
    const messages = await fetchMessages(scope.caseId)
    if (!isCurrentScope(scope)) return
    transcript.value = messages
  }

  async function startCapture() {
    if (!captureAvailable.value) return feedback('连续离线录音 Runtime 当前不可用，请检查 ASR/麦克风能力状态', true)
    if (!canRecord.value) return feedback('请先开始审讯再录音', true)
    if (captureBusy.value || capture.value.running) return

    const scope = currentScope()
    captureBusy.value = true
    try {
      const status = await startAsrCapture(scope.caseId)
      applyCaptureStatus(status, scope)
      feedbackIfCurrent(scope, '录音已开始')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    } finally {
      if (isCurrentScope(scope)) captureBusy.value = false
    }
  }

  /**
   * 停止录音。
   *
   * 返回 true 仅代表"确认已停止"（本来就没在录也算）。失败时必须返回 false，
   * 否则暂停/结束审讯会在录音仍在跑的情况下继续推进，产生"会话已暂停、录音还在
   * 采集"的分裂状态。
   */
  async function stopCapture(_target?: AsrInsertionTarget, showFeedback = true): Promise<boolean> {
    if (!captureAvailable.value || !capture.value.running) return true
    const scope = currentScope()
    if (captureBusy.value) {
      const message = '录音正在停止中，请稍后再试'
      if (isCurrentScope(scope)) capture.value.error = message
      feedbackIfCurrent(scope, message, true)
      return false
    }

    captureBusy.value = true
    try {
      const status = await stopAsrCapture(scope.caseId)
      applyCaptureStatus(status, scope)
      if (status.running) {
        const message = '后端仍报告录音进行中，未能确认停止'
        if (isCurrentScope(scope)) capture.value.error = message
        if (showFeedback) feedbackIfCurrent(scope, message, true)
        return false
      }
      if (showFeedback) feedbackIfCurrent(scope, '录音已停止，识别结果保留为待确认片段，不会自动改写正式笔录')
      return true
    } catch (err) {
      const message = backendErrorMessage(err)
      if (isCurrentScope(scope)) capture.value.error = message
      if (showFeedback) feedbackIfCurrent(scope, message, true)
      return false
    } finally {
      if (isCurrentScope(scope)) captureBusy.value = false
    }
  }

  // Browser audio WS can die mid-session (speech-worker hiccup, network blip).
  // Auto-restart once per failure so a solo tester keeps recording; a 15s
  // cooldown prevents a restart loop if the channel keeps dying.
  let lastAudioRestartAt = 0
  setBrowserAsrUnexpectedCloseListener(() => {
    if (!capture.value.running || captureBusy.value) return
    const scope = currentScope()
    const now = Date.now()
    if (now - lastAudioRestartAt < 15_000) {
      feedbackIfCurrent(scope, '浏览器音频通道再次断开，请手动点击「停止录音」后重新「开始录音」', true)
      return
    }
    lastAudioRestartAt = now
    feedbackIfCurrent(scope, '浏览器音频通道已断开，正在自动重新开始录音…', true)
    void (async () => {
      try {
        await stopCapture(undefined, false)
      } catch {
        // A stop timeout usually means the dead session is being torn down
        // server-side; settle briefly and try to start a fresh capture anyway.
      }
      await new Promise((resolve) => setTimeout(resolve, 1500))
      if (!isCurrentScope(currentScope())) return
      try {
        await startCapture()
      } catch (err) {
        feedbackIfCurrent(currentScope(), `自动重启录音失败：${backendErrorMessage(err)}`, true)
      }
    })()
  })

  setBrowserAsrIncompleteCaptureListener((message) => {
    const scope = currentScope()
    feedbackIfCurrent(scope, `本次录音不完整：${message}`, true)
    if (!captureBusy.value && capture.value.running) {
      void (async () => {
        await stopCapture(undefined, false)
        if (isCurrentScope(scope)) capture.value.error = message
      })()
    }
  })

  async function updatePendingFragment(fragmentId: string, editedText: string, speaker: TemporaryAsrSpeaker) {
    const scope = currentScope()
    try {
      const updated = await updateAsrFragment(scope.caseId, fragmentId, editedText, speaker)
      upsertAsrFragment(updated, scope)
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function confirmPendingFragment(fragmentId: string) {
    const scope = currentScope()
    try {
      const confirmed = await confirmAsrFragment(scope.caseId, fragmentId)
      if (!isCurrentScope(scope) || confirmed.caseId !== scope.caseId) return
      await refreshTranscript(scope)
      if (!isCurrentScope(scope)) return
      capture.value.fragments = capture.value.fragments.filter((fragment) => fragment.id !== confirmed.id)
      selectedFragmentIds.value = selectedFragmentIds.value.filter((id) => id !== confirmed.id)
      feedbackIfCurrent(scope, '片段已确认并写入正式笔录')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function confirmSelectedFragments() {
    if (!selectedFragmentIds.value.length) return

    const scope = currentScope()
    const fragmentIds = [...selectedFragmentIds.value]
    try {
      const result = await confirmAsrFragmentBatch(scope.caseId, fragmentIds)
      if (!isCurrentScope(scope) || result.fragments.some((item) => item.caseId !== scope.caseId)) return
      await refreshTranscript(scope)
      if (!isCurrentScope(scope)) return
      const confirmedIds = new Set(result.fragments.map((item) => item.id))
      capture.value.fragments = capture.value.fragments.filter((fragment) => !confirmedIds.has(fragment.id))
      selectedFragmentIds.value = selectedFragmentIds.value.filter((id) => !confirmedIds.has(id))
      feedbackIfCurrent(scope, `已确认并入库 ${result.confirmedCount} 条片段`)
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function discardPendingFragment(fragmentId: string) {
    const scope = currentScope()
    try {
      const discarded = await discardAsrFragment(scope.caseId, fragmentId)
      if (!isCurrentScope(scope) || discarded.caseId !== scope.caseId) return
      capture.value.fragments = capture.value.fragments.filter((fragment) => fragment.id !== fragmentId)
      selectedFragmentIds.value = selectedFragmentIds.value.filter((id) => id !== fragmentId)
      feedbackIfCurrent(scope, '临时片段已丢弃')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  function toggleFragmentSelection(fragmentId: string) {
    selectedFragmentIds.value = selectedFragmentIds.value.includes(fragmentId)
      ? selectedFragmentIds.value.filter((id) => id !== fragmentId)
      : [...selectedFragmentIds.value, fragmentId]
  }

  async function refreshCase(scope = currentScope()) {
    const summary = await fetchCase(scope.caseId)
    if (!isCurrentScope(scope) || summary.id !== scope.caseId) return
    caseSummary.value = summary
  }

  async function refreshVoiceprintState(scope = currentScope()) {
    const [readiness, officers] = await Promise.all([
      fetchVoiceprintReadiness(scope.caseId),
      fetchOfficerVoiceprints(true),
    ])
    if (!isCurrentScope(scope)) return
    voiceprintReadiness.value = readiness
    officerVoiceprints.value = officers
  }

  function stopVoiceprintProgressPolling() {
    if (voiceprintProgressTimer) clearInterval(voiceprintProgressTimer)
    voiceprintProgressTimer = undefined
  }

  async function refreshVoiceprintCaptureProgress(scope: CaseScope) {
    if (!isCurrentScope(scope) || voiceprintEnrollmentState.value.phase !== 'RECORDING') return
    try {
      const status = await fetchVoiceprintEnrollmentStatus()
      if (!isCurrentScope(scope) || voiceprintEnrollmentState.value.phase !== 'RECORDING') return
      if (!status.active || status.subjectId !== voiceprintEnrollmentState.value.subjectId) return
      voiceprintEnrollmentState.value = {
        ...voiceprintEnrollmentState.value,
        capturedDurationMs: status.capturedDurationMs,
        targetDurationMs: status.targetDurationMs,
        captureComplete: status.complete,
      }
      if (!status.complete) return
      stopVoiceprintProgressPolling()
      if (voiceprintEnrollmentState.value.kind === 'SUSPECT') {
        await stopSuspectVoiceprintEnrollment()
      } else if (voiceprintEnrollmentState.value.kind === 'OFFICER' && voiceprintEnrollmentState.value.subjectId) {
        await stopOfficerVoiceprintEnrollment(voiceprintEnrollmentState.value.subjectId)
      }
    } catch (err) {
      if (!isCurrentScope(scope)) return
      stopVoiceprintProgressPolling()
      voiceprintEnrollmentState.value = { ...voiceprintEnrollmentState.value, phase: 'ERROR', message: backendErrorMessage(err) }
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  function startVoiceprintProgressPolling(scope: CaseScope) {
    stopVoiceprintProgressPolling()
    void refreshVoiceprintCaptureProgress(scope)
    voiceprintProgressTimer = setInterval(() => { void refreshVoiceprintCaptureProgress(scope) }, 500)
  }

  function selectInterrogatorOfficer(officerId: string | null) {
    selectedInterrogatorOfficerId.value = officerId || null
    setCurrentOperator(selectedInterrogatorOfficerId.value)
  }

  function selectRecorderOfficer(officerId: string | null) {
    selectedRecorderOfficerId.value = officerId || null
  }

  async function startSuspectVoiceprintEnrollment(actorId?: string) {
    if (voiceprintBusy.value) return
    const scope = currentScope()
    voiceprintBusy.value = true
    voiceprintEnrollmentState.value = { phase: 'RECORDING', kind: 'SUSPECT', subjectId: scope.caseId, message: '正在录制嫌疑人声纹' }
    try {
      const result = await startSuspectVoiceprintEnrollmentApi(scope.caseId, actorId)
      if (!isCurrentScope(scope)) return
      voiceprintEnrollmentState.value = {
        ...voiceprintEnrollmentState.value,
        phase: 'RECORDING',
        simulated: Boolean(result.simulated),
      }
      startVoiceprintProgressPolling(scope)
    } catch (err) {
      if (isCurrentScope(scope)) voiceprintEnrollmentState.value = { phase: 'ERROR', kind: 'SUSPECT', subjectId: scope.caseId, message: backendErrorMessage(err) }
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    } finally {
      if (isCurrentScope(scope)) voiceprintBusy.value = false
    }
  }

  async function stopSuspectVoiceprintEnrollment(actorId?: string) {
    if (voiceprintBusy.value) return
    stopVoiceprintProgressPolling()
    const scope = currentScope()
    voiceprintBusy.value = true
    voiceprintEnrollmentState.value = { ...voiceprintEnrollmentState.value, phase: 'PROCESSING' }
    try {
      const result = await stopSuspectVoiceprintEnrollmentApi(scope.caseId, actorId)
      if (!isCurrentScope(scope)) return
      await refreshVoiceprintState(scope)
      if (!isCurrentScope(scope)) return
      voiceprintEnrollmentState.value = {
        phase: 'COMPLETE',
        kind: 'SUSPECT',
        subjectId: scope.caseId,
        usableDurationMs: Number(result.usableDurationMs ?? 0),
        simulated: Boolean(result.simulated),
        message: result.simulated ? '浏览器开发模拟完成；未形成真实声纹验证' : '嫌疑人声纹已注册',
      }
      feedbackIfCurrent(scope, voiceprintEnrollmentState.value.message || '嫌疑人声纹已注册')
    } catch (err) {
      if (isCurrentScope(scope)) voiceprintEnrollmentState.value = { phase: 'ERROR', kind: 'SUSPECT', subjectId: scope.caseId, message: backendErrorMessage(err) }
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    } finally {
      if (isCurrentScope(scope)) voiceprintBusy.value = false
    }
  }

  async function startOfficerVoiceprintEnrollment(officerId: string, officerName: string, actorId?: string) {
    if (voiceprintBusy.value) return
    const scope = currentScope()
    voiceprintBusy.value = true
    voiceprintEnrollmentState.value = { phase: 'RECORDING', kind: 'OFFICER', subjectId: officerId, officerName, message: '正在录制民警声纹' }
    try {
      const result = await startOfficerVoiceprintEnrollmentApi(officerId, officerName, actorId)
      if (!isCurrentScope(scope)) return
      voiceprintEnrollmentState.value = { ...voiceprintEnrollmentState.value, phase: 'RECORDING', simulated: Boolean(result.simulated) }
      startVoiceprintProgressPolling(scope)
    } catch (err) {
      if (isCurrentScope(scope)) voiceprintEnrollmentState.value = { phase: 'ERROR', kind: 'OFFICER', subjectId: officerId, officerName, message: backendErrorMessage(err) }
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    } finally {
      if (isCurrentScope(scope)) voiceprintBusy.value = false
    }
  }

  async function stopOfficerVoiceprintEnrollment(officerId: string, actorId?: string) {
    if (voiceprintBusy.value) return
    stopVoiceprintProgressPolling()
    const scope = currentScope()
    voiceprintBusy.value = true
    voiceprintEnrollmentState.value = { ...voiceprintEnrollmentState.value, phase: 'PROCESSING' }
    try {
      const result = await stopOfficerVoiceprintEnrollmentApi(officerId, actorId)
      if (!isCurrentScope(scope)) return
      await refreshVoiceprintState(scope)
      if (!isCurrentScope(scope)) return
      voiceprintEnrollmentState.value = {
        phase: 'COMPLETE',
        kind: 'OFFICER',
        subjectId: officerId,
        officerName: String(result.officerName ?? voiceprintEnrollmentState.value.officerName ?? ''),
        usableDurationMs: Number(result.usableDurationMs ?? 0),
        simulated: Boolean(result.simulated),
        message: result.simulated ? '浏览器开发模拟完成；未形成真实民警声纹' : '民警声纹已保存',
      }
      feedbackIfCurrent(scope, voiceprintEnrollmentState.value.message || '民警声纹已保存')
    } catch (err) {
      if (isCurrentScope(scope)) voiceprintEnrollmentState.value = { ...voiceprintEnrollmentState.value, phase: 'ERROR', message: backendErrorMessage(err) }
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    } finally {
      if (isCurrentScope(scope)) voiceprintBusy.value = false
    }
  }

  async function revokeOfficerVoiceprint(officerId: string, actorId?: string) {
    const scope = currentScope()
    try {
      await revokeOfficerVoiceprintApi(officerId, actorId)
      if (!isCurrentScope(scope)) return
      if (selectedInterrogatorOfficerId.value === officerId) selectedInterrogatorOfficerId.value = null
      if (selectedRecorderOfficerId.value === officerId) selectedRecorderOfficerId.value = null
      await refreshVoiceprintState(scope)
      feedbackIfCurrent(scope, '民警声纹已撤销')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function bindVoiceprintRoles(actorId?: string) {
    const scope = currentScope()
    try {
      const draft = await updateVoiceprintRoleDraft(
        scope.caseId,
        selectedInterrogatorOfficerId.value,
        selectedRecorderOfficerId.value,
        actorId,
      )
      if (!isCurrentScope(scope)) return
      selectedInterrogatorOfficerId.value = draft.interrogatorOfficerId
      selectedRecorderOfficerId.value = draft.recorderOfficerId
      setCurrentOperator(draft.interrogatorOfficerId)
      if (session.value.status === 'READY') {
        feedbackIfCurrent(scope, '案件级民警角色草稿已保存；开始审讯后会绑定到本次 session')
        return
      }
      const readiness = await updateVoiceprintAssignments(
        scope.caseId,
        selectedInterrogatorOfficerId.value,
        selectedRecorderOfficerId.value,
        actorId,
      )
      if (!isCurrentScope(scope)) return
      voiceprintReadiness.value = readiness
      feedbackIfCurrent(scope, '本次审讯的民警声纹角色已绑定')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
      throw err
    }
  }

  async function ask(text: string) {
    const clean = text.trim()
    if (!clean || streaming.value) return
    if (!canRecord.value) {
      feedback(session.value.status === 'PAUSED' ? '审讯已暂停，请先恢复' : '请先点击“开始审讯”', true)
      return
    }

    const scope = currentScope()
    error.value = ''
    actionError.value = ''
    try {
      const persisted = await persistQuestionOrAnswer(scope.caseId, clean, '民警')
      if (!isCurrentScope(scope)) return
      transcript.value.push(persisted)
      feedbackIfCurrent(scope, `Q${persisted.seq || transcript.value.length} 已保存`)
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
      return
    }

    if (!isCurrentScope(scope)) return
  }

  async function editMessage(messageId: string, text: string) {
    const scope = currentScope()
    try {
      const updated = await updateTranscriptMessage(scope.caseId, messageId, text)
      if (!isCurrentScope(scope)) return
      const index = transcript.value.findIndex((item) => item.id === messageId)
      if (index >= 0) transcript.value[index] = updated
      feedbackIfCurrent(scope, `Q/A ${updated.seq || ''} 已修订，旧内容已进入版本历史`)
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function markMessage(messageId: string) {
    const scope = currentScope()
    try {
      const updated = await markTranscriptMessage(scope.caseId, messageId, 'conflict')
      if (!isCurrentScope(scope)) return
      const index = transcript.value.findIndex((item) => item.id === messageId)
      if (index >= 0) transcript.value[index] = updated
      feedbackIfCurrent(scope, '已标记为“存在矛盾”，后端审计日志已记录')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function markLatestConflict() {
    const target = [...transcript.value].reverse().find((item) => item.speaker !== 'AI')
    if (!target) return feedback('当前没有可标记的正式问答', true)
    await markMessage(target.id)
  }

  async function openRevisions(messageId?: string) {
    const scope = currentScope()
    try {
      const nextRevisions = await fetchRevisions(scope.caseId, messageId)
      if (!isCurrentScope(scope)) return
      revisions.value = nextRevisions
      revisionsOpen.value = true
      feedbackIfCurrent(scope, revisions.value.length ? `已读取 ${revisions.value.length} 条版本记录` : '当前暂无修订历史')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  function closeRevisions() {
    revisionsOpen.value = false
  }

  async function startSession() {
    const scope = currentScope()
    try {
      // 声纹已移出办理流程，开始询问不再绑定民警声纹角色。
      const nextSession = await startSessionApi(scope.caseId, null, null)
      if (!isCurrentScope(scope) || nextSession.caseId !== scope.caseId) return
      session.value = nextSession
      if (!isCurrentScope(scope)) return
      disposeCaptureEvents()
      initializeRuntimeEvents(scope)
      await refreshCase(scope)
      feedbackIfCurrent(scope, '询问已开始')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  /**
   * 暂停/结束前的前置条件：先确认录音真的停了。
   *
   * 停不下来就中止操作并说明原因 —— 否则会出现"会话已暂停/结束、录音还在采集"
   * 的分裂状态，后端还会继续往这个会话里写片段。
   */
  async function ensureCaptureStopped(scope: CaseScope, action: string): Promise<boolean> {
    if (!capture.value.running) return true
    const stopped = await stopCapture(undefined, false)
    if (!isCurrentScope(scope)) return false
    if (stopped) return true
    const reason = capture.value.error ? `（${capture.value.error}）` : ''
    feedbackIfCurrent(scope, `停止录音失败${reason}，已取消${action}审讯；请先手动停止录音再重试`, true)
    return false
  }

  async function togglePause() {
    const scope = currentScope()
    try {
      if (session.value.status === 'RUNNING') {
        if (!(await ensureCaptureStopped(scope, '暂停'))) return
        const nextSession = await pauseSessionApi(scope.caseId)
        if (!isCurrentScope(scope) || nextSession.caseId !== scope.caseId) return
        session.value = nextSession
        feedbackIfCurrent(scope, '审讯已暂停，新的正式问答将被后端拒绝')
      } else if (session.value.status === 'PAUSED') {
        const nextSession = await resumeSessionApi(scope.caseId)
        if (!isCurrentScope(scope) || nextSession.caseId !== scope.caseId) return
        session.value = nextSession
        feedbackIfCurrent(scope, '审讯已恢复')
      }
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function finishSession() {
    const scope = currentScope()
    try {
      if (!(await ensureCaptureStopped(scope, '结束'))) return
      const nextSession = await finishSessionApi(scope.caseId)
      if (!isCurrentScope(scope) || nextSession.caseId !== scope.caseId) return
      session.value = nextSession
      await refreshCase(scope)
      feedbackIfCurrent(scope, '本次审讯已结束并进入复核状态')
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function nextStage() {
    const index = stageOrder.indexOf(session.value.stage)
    if (index < 0 || index >= stageOrder.length - 1) return feedback('当前已经是最后的“确认签名”阶段', true)

    const scope = currentScope()
    try {
      const nextSession = await changeSessionStage(scope.caseId, stageOrder[index + 1])
      if (!isCurrentScope(scope) || nextSession.caseId !== scope.caseId) return
      session.value = nextSession
      await refreshCase(scope)
      feedbackIfCurrent(scope, `已进入：${stageTextMap[nextSession.stage]}`)
    } catch (err) {
      feedbackIfCurrent(scope, backendErrorMessage(err), true)
    }
  }

  async function useSuggestion(text: string) {
    feedback('已采用事实核对中的追问建议')
    await ask(text)
  }

  return {
    caseId,
    loading,
    caseSummary,
    session,
    transcript,
    facts,
    completion,
    stateText,
    stageText,
    canRecord,
    streaming,
    error,
    actionMessage,
    actionError,
    revisions,
    revisionsOpen,
    nativeCaptureAvailable: captureAvailable,
    capture,
    activeFragments,
    fragmentHistory,
    hydrateFragmentHistory,
    applyCaptureEvent,
    formalRecordRevision,
    captureBusy,
    captureInsertionReceipt,
    captureElapsedMs,
    selectedFragmentIds,
    voiceprintReadiness,
    officerVoiceprints,
    selectedInterrogatorOfficerId,
    selectedRecorderOfficerId,
    voiceprintEnrollmentState,
    voiceprintBusy,
    resetCaseContext,
    initialize,
    ask,
    editMessage,
    markMessage,
    markLatestConflict,
    openRevisions,
    closeRevisions,
    startSession,
    togglePause,
    finishSession,
    nextStage,
    useSuggestion,
    startCapture,
    stopCapture,
    applySessionState,
    applyStateSync,
    updatePendingFragment,
    confirmPendingFragment,
    confirmSelectedFragments,
    discardPendingFragment,
    toggleFragmentSelection,
    refreshVoiceprintState,
    selectInterrogatorOfficer,
    selectRecorderOfficer,
    startSuspectVoiceprintEnrollment,
    stopSuspectVoiceprintEnrollment,
    startOfficerVoiceprintEnrollment,
    stopOfficerVoiceprintEnrollment,
    revokeOfficerVoiceprint,
    bindVoiceprintRoles,
    disposeCaptureEvents,
    feedback,
  }
})
