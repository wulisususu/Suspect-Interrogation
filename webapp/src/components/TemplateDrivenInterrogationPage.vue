<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { backendErrorMessage, confirmAsrFragmentBatch, discardAsrFragment } from '../api/interrogation'
import { markReportGenerated } from '../api/archive'
import { fetchDocumentSigningState, finalizeDocument, signDocument } from '../api/documentSigning'
import type {
  AsrCaptureStatus,
  AsrInsertionTarget,
  CaseSummary,
  DocumentSignerRole,
  DocumentSigningState,
  FactItem,
  SessionState,
  TemporaryAsrFragment,
  TemporaryAsrSpeaker,
} from '../types/interrogation'
import type {
  CaseQuestionCreateInput,
  CaseQuestionUpdateInput,
  PendingResolution,
  QAUnitResolution,
  RoundReassociateInput,
  StandardQuestion,
  TemplateWorkspace,
} from '../types/templateInterrogation'
import LongPressButton from './LongPressButton.vue'
import DictationRecordPreview from './DictationRecordPreview.vue'
import DraftQuestionRail from './DraftQuestionRail.vue'
import FactCoverageBar from './FactCoverageBar.vue'
import RecordArchivePage from './RecordArchivePage.vue'
import RecordReviewPanel from './RecordReviewPanel.vue'
import ReviewChecklistPanel from './ReviewChecklistPanel.vue'
import ReviewRecordPreview from './ReviewRecordPreview.vue'
import RecordSigningPage from './RecordSigningPage.vue'
import type { RecordMode } from '../flow/steps'
import { cssToken } from '../utils/cssToken'
import { reviewAutoChecks } from '../utils/reviewChecks'
import { factCoverage } from '../utils/factCoverage'
import { TEMPLATE_CATALOG } from '../config/templateCatalog'
import { freezeBlockReason, orderedReviewFragments } from '../utils/recordCompletion'
import './templateInterrogation.css'

const props = defineProps<{
  caseId: string
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  capture: AsrCaptureStatus
  canRecord: boolean
  nativeCaptureAvailable: boolean
  captureBusy: boolean
  captureElapsedMs: number
  workspace: TemplateWorkspace
  dialogueHistory: TemporaryAsrFragment[]
  fragmentHistory: (fragmentId: string) => TemporaryAsrFragment[]
  questionLibrary: StandardQuestion[]
  templateBusy: boolean
  templateError: string
  questionDictationAvailable: boolean
  questionDictationActive: boolean
  questionDictationBusy: boolean
  questionDictationDraft: string
  questionDictationError: string
  recorderName?: string
  /** 逐题录音：正在为哪道题录音、是否在按住说话追加一问、本次录音的实时文字 */
  recordingQuestionId?: string | null
  questionRecording?: boolean
  liveText?: string
  completionMode: RecordMode
  officers?: Array<{ officerId: string; officerName: string }>
}>()

const emit = defineEmits<{
  saved: []
  captureStart: []
  captureStop: [target?: AsrInsertionTarget]
  questionDictationStart: []
  questionDictationStop: []
  loadLibrary: [category?: string]
  createQuestion: [input: CaseQuestionCreateInput]
  updateQuestion: [questionId: string, input: CaseQuestionUpdateInput]
  reorderQuestions: [questionIds: string[]]
  removeQuestion: [questionId: string]
  resolvePending: [pendingId: string, resolution: PendingResolution]
  resolveQaUnit: [qaUnitId: string, resolution: QAUnitResolution]
  rollbackQaUnit: [qaUnitId: string]
  reassociateRound: [roundId: string, input: RoundReassociateInput]
  updateAnswer: [roundId: string, answerText: string]
  attachFragmentAnswer: [questionId: string, fragmentIds: string[]]
  createLiveQuestionFromFragments: [fragmentIds: string[], afterQuestionId: string | null]
  print: []
  saveLibrary: [questionId: string]
  correctFragment: [fragmentId: string, speaker: TemporaryAsrSpeaker, reason: string, text?: string]
  updateHeader: [target: 'case' | 'fact', key: string, value: string]
  'update:completionMode': [mode: RecordMode]
  back: []
  answerStart: [questionId: string, replace: boolean]
  answerStop: []
  questionHoldStart: [afterQuestionId: string | null]
  questionHoldEnd: []
  togglePause: []
}>()

const missingElements = computed(() => factCoverage(props.facts).missing.length)
const templateTitle = computed(() => TEMPLATE_CATALOG.find((item) => item.backendKey === props.workspace.templateKey)?.title || '嫌疑人询问')
/** 正本的最近保存时间：取问题与问答轮次的最新更新时间。 */
const savedAtText = computed(() => {
  const stamps = [...props.workspace.questions.map((item) => item.updatedAt), ...props.workspace.rounds.map((item) => item.updatedAt)]
    .map((value) => (value ? Date.parse(value) : NaN))
    .filter((value) => Number.isFinite(value))
  if (!stamps.length) return ''
  const date = new Date(Math.max(...stamps))
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
})

type SignaturePoint = { x: number; y: number; t: number; p: number }

const signingState = ref<DocumentSigningState | null>(null)
const signingBusy = ref('')
const signingError = ref('')
const signingLoading = ref(true)
const signingLoadError = ref('')
const reviewBusy = ref(false)
const mode = computed<RecordMode>({
  get: () => props.completionMode,
  set: (value) => emit('update:completionMode', value),
})
let signingRequest = 0
/** 逐题录音已挂到题目回答上的片段视为已处理（与后端冻结校验一致），不再列入待确认转写。 */
const attachedFragmentIds = computed(() => new Set(props.workspace.rounds
  .filter((round) => round.status !== 'DETACHED')
  .flatMap((round) => round.answerFragmentIds)))
const reviewFragments = computed(() => orderedReviewFragments(props.dialogueHistory, false)
  .filter((item) => !attachedFragmentIds.value.has(item.id)))
const unresolvedFragments = computed(() => reviewFragments.value.filter(item => item.state !== 'CONFIRMED' || !item.confirmedMessageId).length)
const unresolvedQa = computed(() => props.workspace.qaUnits.filter(item => ['OPEN', 'CLOSED', 'ROUTING', 'NEEDS_REVIEW'].includes(item.status)).length)
const completionBusy = computed(() => props.templateBusy || props.captureBusy || reviewBusy.value || !!signingBusy.value)
const freezeReason = computed(() => freezeBlockReason({
  sessionStatus: props.session.status, captureRunning: props.capture.running, busy: completionBusy.value,
  loading: signingLoading.value, loadError: signingLoadError.value, frozen: documentFrozen.value,
  unresolvedFragments: unresolvedFragments.value, unresolvedQa: unresolvedQa.value,
  recordError: props.templateError || (props.workspace.caseId !== props.caseId ? '笔录尚未读取' : ''), hasQuestions: props.workspace.questions.length > 0,
  asrStatus: props.capture.asrStatus, speakerStatus: props.capture.speakerStatus, recordingStatus: props.capture.recordingStatus,
}))
const signatureRole = ref<DocumentSignerRole | null>(null)
const signatureCanvas = ref<HTMLCanvasElement | null>(null)
const signatureStrokes = ref<SignaturePoint[][]>([])
let activeStroke: SignaturePoint[] | null = null

const autoChecks = computed(() => reviewAutoChecks(props.facts, props.summary, props.recorderName ?? ''))
const documentFrozen = computed(() => !!signingState.value || ['FROZEN', 'SIGNED', 'REPORT_GENERATED'].includes(props.summary.workflowState || ''))
const documentLocked = computed(() => signingState.value?.status === 'LOCKED')

watch(
  () => props.caseId,
  () => {
    signingState.value = null
    signingBusy.value = ''
    reviewBusy.value = false
    signatureRole.value = null
    signatureStrokes.value = []
    mode.value = props.session.status === 'COMPLETED' ? 'review' : 'interrogation'
    void loadSigningState()
  },
  { immediate: true },
)
watch(() => props.session.status, (status) => {
  if (status === 'COMPLETED' && mode.value === 'interrogation') mode.value = 'review'
})

async function loadSigningState() {
  const request = ++signingRequest
  const caseId = props.caseId
  signingError.value = ''
  signingLoadError.value = ''
  signingLoading.value = true
  if (!caseId) {
    signingState.value = null
    signingLoading.value = false
    return
  }
  try {
    const state = await fetchDocumentSigningState(caseId)
    if (request !== signingRequest || props.caseId !== caseId) return
    signingState.value = state
    // 已归档案件直接落到导出页，别再让人以为还要签名
    if (state) mode.value = props.summary.workflowState === 'REPORT_GENERATED' ? 'archive' : 'sign'
  } catch (err) {
    if (request !== signingRequest || props.caseId !== caseId) return
    signingLoadError.value = backendErrorMessage(err)
  } finally {
    if (request === signingRequest && props.caseId === caseId) signingLoading.value = false
  }
}

async function reviewAction(ids: string[], discard = false) {
  if (completionBusy.value || documentFrozen.value || signingLoading.value || signingLoadError.value || !ids.length) return
  const caseId = props.caseId
  const request = signingRequest
  reviewBusy.value = true
  signingError.value = ''
  try {
    if (discard) await discardAsrFragment(caseId, ids[0]!)
    else await confirmAsrFragmentBatch(caseId, ids)
    if (caseId === props.caseId && request === signingRequest) emit('saved')
  } catch (err) {
    if (caseId === props.caseId && request === signingRequest) signingError.value = backendErrorMessage(err)
  } finally {
    if (caseId === props.caseId && request === signingRequest) reviewBusy.value = false
  }
}

function locateQuestion(questionId: string) {
  const target = document.querySelector<HTMLElement>(`[data-question-id="${questionId}"]`)
  if (!target) return
  target.scrollIntoView({ block: 'center', behavior: 'smooth' })
  target.classList.add('record-qa-located')
  window.setTimeout(() => target.classList.remove('record-qa-located'), 1600)
}

async function finishAndFreeze() {
  if (freezeReason.value) { signingError.value = freezeReason.value; return }
  const caseId = props.caseId
  const request = signingRequest
  signingBusy.value = 'freeze'
  signingError.value = ''
  try {
    const state = await finalizeDocument(caseId)
    if (caseId !== props.caseId || request !== signingRequest) return
    signingState.value = state
    mode.value = 'sign'
    emit('saved')
  } catch (err) {
    if (caseId === props.caseId && request === signingRequest) signingError.value = backendErrorMessage(err)
  } finally {
    if (caseId === props.caseId && request === signingRequest) signingBusy.value = ''
  }
}

const archiving = ref(false)

/** 签名齐备后确认归档：后端 SIGNED → REPORT_GENERATED，前端随后给出导出页 */
async function archiveCase() {
  if (archiving.value) return
  const caseId = props.caseId
  archiving.value = true
  signingError.value = ''
  try {
    await markReportGenerated(caseId)
    if (caseId !== props.caseId) return
    const state = await fetchDocumentSigningState(caseId)
    if (caseId !== props.caseId) return
    signingState.value = state ?? signingState.value
    mode.value = 'archive'
    emit('saved')
  } catch (err) {
    if (caseId === props.caseId) signingError.value = backendErrorMessage(err)
  } finally {
    if (caseId === props.caseId) archiving.value = false
  }
}

function signatureFor(role: DocumentSignerRole) {
  return signingState.value?.signatures.find((item) => item.signerRole === role)
}

function signerName(role: DocumentSignerRole) {
  return role === 'SUSPECT' ? (props.summary.suspectName || '被讯问人') : (props.summary.officerName || '询问人')
}

async function openSignature(role: DocumentSignerRole) {
  if (!signingState.value) {
    signingError.value = '请先结束审讯并冻结正式笔录。'
    return
  }
  if (!signingState.value.integrityValid) {
    signingError.value = '当前冻结版本完整性校验失败，不能继续签名。'
    return
  }
  if (signatureFor(role)) return
  signatureRole.value = role
  signatureStrokes.value = []
  activeStroke = null
  await nextTick()
  prepareCanvas()
}

function closeSignature() {
  if (signingBusy.value === 'sign') return
  signatureRole.value = null
  signatureStrokes.value = []
  activeStroke = null
}

function prepareCanvas() {
  const canvas = signatureCanvas.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const ratio = Math.max(1, window.devicePixelRatio || 1)
  canvas.width = Math.max(1, Math.round(rect.width * ratio))
  canvas.height = Math.max(1, Math.round(rect.height * ratio))
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  ctx.clearRect(0, 0, rect.width, rect.height)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = cssToken('--paper-ink', '#242b35')
}

function pointFromEvent(event: PointerEvent): SignaturePoint {
  const rect = signatureCanvas.value?.getBoundingClientRect()
  return { x: event.clientX - (rect?.left || 0), y: event.clientY - (rect?.top || 0), t: Date.now(), p: event.pressure || 0.5 }
}

function drawSegment(from: SignaturePoint, to: SignaturePoint) {
  const ctx = signatureCanvas.value?.getContext('2d')
  if (!ctx) return
  ctx.lineWidth = 1.7 + Math.min(1, to.p || 0.5) * 1.8
  ctx.beginPath()
  ctx.moveTo(from.x, from.y)
  ctx.lineTo(to.x, to.y)
  ctx.stroke()
}

function startSignatureStroke(event: PointerEvent) {
  const canvas = signatureCanvas.value
  if (!canvas) return
  canvas.setPointerCapture(event.pointerId)
  const point = pointFromEvent(event)
  activeStroke = [point]
  signatureStrokes.value.push(activeStroke)
}

function moveSignatureStroke(event: PointerEvent) {
  if (!activeStroke) return
  const next = pointFromEvent(event)
  const previous = activeStroke[activeStroke.length - 1]
  activeStroke.push(next)
  drawSegment(previous, next)
}

function endSignatureStroke(event: PointerEvent) {
  const canvas = signatureCanvas.value
  if (canvas?.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
  activeStroke = null
}

function clearSignature() {
  signatureStrokes.value = []
  activeStroke = null
  prepareCanvas()
}

async function confirmSignature() {
  const caseId = props.caseId
  const request = signingRequest
  const role = signatureRole.value
  const canvas = signatureCanvas.value
  const hasInk = signatureStrokes.value.some((stroke) => stroke.length > 1)
  if (!role || !canvas || !hasInk) {
    signingError.value = '请先在签名区域完成手写签名。'
    return
  }

  signingBusy.value = 'sign'
  signingError.value = ''
  try {
    const state = await signDocument(
      caseId,
      role,
      signerName(role),
      canvas.toDataURL('image/png'),
      JSON.stringify(signatureStrokes.value),
    )
    if (caseId !== props.caseId || request !== signingRequest) return
    signingState.value = state
    signatureRole.value = null
    signatureStrokes.value = []
    emit('saved')
  } catch (err) {
    if (caseId === props.caseId && request === signingRequest) signingError.value = backendErrorMessage(err)
  } finally {
    if (caseId === props.caseId && request === signingRequest) signingBusy.value = ''
  }
}
</script>

<template>
  <section class="template-driven-interrogation-page" :class="{ 'record-completion-mode': mode !== 'interrogation' }">
    <p v-if="templateError || signingError || signingLoadError" class="template-page-error" role="alert">{{ templateError || signingError || signingLoadError }}<button v-if="signingLoadError" :disabled="signingLoading" @click="loadSigningState">重新读取签署状态</button></p>
    <header v-if="mode === 'sign' || mode === 'archive'" class="record-completion-heading record-no-print"><h1>签署归档 · {{ documentFrozen ? documentLocked ? '签署完成' : '已冻结' : session.status === 'COMPLETED' ? '审讯已结束' : '待冻结' }}</h1><p>{{ summary.id }} · {{ summary.suspectName || '姓名未填写' }} · 待确认转写 {{ unresolvedFragments }} 条 · 待处理问答 {{ unresolvedQa }} 组</p></header>

    <RecordSigningPage
      v-if="mode === 'sign'"
      :summary="summary"
      :facts="facts"
      :session="session"
      :questions="workspace.questions"
      :signing-state="signingState"
      :busy="completionBusy || signingLoading"
      :archiving="archiving"
      :officers="officers ?? []"
      @print="emit('print')"
      @sign="openSignature"
      @archive="archiveCase"
    />

    <RecordArchivePage
      v-else-if="mode === 'archive'"
      :summary="summary"
      :facts="facts"
      :session="session"
      :questions="workspace.questions"
      :signing-state="signingState"
      :archived="summary.workflowState === 'REPORT_GENERATED'"
      @print="emit('print')"
      @back="emit('back')"
      @sign="mode = 'sign'"
    />

    <header v-if="mode === 'interrogation'" class="dictation-heading record-no-print">
      <div>
        <h1>③ 智能工作台 · 问答录入</h1>
        <p>左栏操作作答与归纳 · 右栏实时预览正本 · 整理定稿由民警完成</p>
      </div>
      <span class="dictation-mode">人工操作模式 · 正式询问</span>
      <button type="button" class="dictation-finalize" :disabled="!!recordingQuestionId || questionRecording" @click="mode = 'review'">{{ missingElements ? `定稿并校验 · 缺 ${missingElements} 项` : '定稿并校验' }}</button>
    </header>

    <div v-if="mode === 'interrogation'" class="template-interrogation-grid draft-first">
      <div class="formal-column is-dictation">
        <header class="formal-heading record-no-print">
          <strong>正本 · 询问笔录</strong>
          <span class="formal-template-chip">模板 · {{ templateTitle }}</span>
          <small v-if="savedAtText">已自动保存 · {{ savedAtText }}</small>
        </header>
        <FactCoverageBar :facts="facts" @fill="mode = 'review'" />
        <DictationRecordPreview
          :summary="summary"
          :facts="facts"
          :session="session"
          :questions="workspace.questions"
          :busy="templateBusy"
          :locked="documentFrozen"
          @commit="(questionId, text) => emit('updateAnswer', questionId, text)"
        />
      </div>

      <div class="dialogue-column draft-column">
        <DraftQuestionRail
          :questions="workspace.questions"
          :session-status="session.status"
          :recording-question-id="recordingQuestionId ?? null"
          :question-recording="questionRecording"
          :capture-busy="captureBusy"
          :capture-available="nativeCaptureAvailable"
          :capture-elapsed-ms="captureElapsedMs"
          :audio-levels="capture.audioLevels"
          :live-text="liveText"
          :locked="documentFrozen || templateBusy"
          @locate="locateQuestion"
          @record="(questionId, replace) => emit('answerStart', questionId, replace)"
          @stop="emit('answerStop')"
          @commit="(questionId, text) => emit('updateAnswer', questionId, text)"
          @update-draft="(roundId, text) => emit('updateAnswer', roundId, text)"
          @update-answer="(questionId, text) => emit('updateAnswer', questionId, text)"
          @add-question="(text, afterQuestionId) => emit('createQuestion', { text, source: 'LIVE', afterQuestionId })"
          @question-hold-start="emit('questionHoldStart', $event)"
          @question-hold-end="emit('questionHoldEnd')"
          @toggle-pause="emit('togglePause')"
        />
      </div>
    </div>

    <template v-if="mode === 'review'">
      <header class="dictation-heading record-no-print">
        <div>
          <h1>④ 定稿校验</h1>
          <p>核对核心要素与未获取项，补齐或如实标注后定稿；定稿后笔录冻结</p>
        </div>
        <span class="dictation-mode">人工操作模式 · 正式询问</span>
        <template v-if="!documentFrozen">
          <button type="button" class="review-back" :disabled="!!signingBusy" @click="mode = 'interrogation'">返回修改</button>
          <LongPressButton class="dictation-finalize" :disabled="!!freezeReason" @confirm="finishAndFreeze">{{ signingBusy === 'freeze' ? '正在定稿…' : '确认定稿' }}</LongPressButton>
        </template>
        <button v-else type="button" class="dictation-finalize" @click="mode = 'sign'">进入签署归档 →</button>
      </header>

      <div class="review-layout">
        <div class="review-left">
          <ReviewChecklistPanel
            :summary="summary"
            :facts="facts"
            :questions="workspace.questions"
            :template-title="templateTitle"
            :block-reason="freezeReason"
            :frozen="documentFrozen"
            :unresolved-fragments="unresolvedFragments"
            :unresolved-qa="unresolvedQa"
            :auto-checks="autoChecks"
          />
          <details v-if="unresolvedFragments || unresolvedQa" class="raw-transcript review-fragments">
            <summary>处理未完成的转写 {{ unresolvedFragments }} 条 · 问答 {{ unresolvedQa }} 组</summary>
            <RecordReviewPanel :fragments="reviewFragments" :qa-units="workspace.qaUnits" :busy="completionBusy || signingLoading || !!signingLoadError" :frozen="documentFrozen" @confirm="reviewAction($event)" @discard="reviewAction([$event], true)" @resolve-qa-unit="(id, resolution) => emit('resolveQaUnit', id, resolution)" @correct="(id, speaker, reason, text) => emit('correctFragment', id, speaker, reason, text)" />
          </details>
        </div>
        <ReviewRecordPreview :questions="workspace.questions" />
      </div>

      <footer class="review-footer record-no-print">
        <span>定稿后笔录即冻结，不可再编辑；签名与指纹在 ⑤ 签署归档完成<template v-if="!documentFrozen"> · 长按「确认定稿」0.8 秒即定稿</template></span>
        <span v-if="savedAtText">已自动保存 · {{ savedAtText }}</span>
      </footer>
    </template>

    <div v-if="signatureRole" class="signature-modal" role="dialog" aria-modal="true" aria-label="电子签名">
      <section class="signature-dialog">
        <header>
          <div>
            <span class="panel-kicker">冻结版本签名</span>
            <h2>{{ signatureRole === 'SUSPECT' ? '被讯问人签名' : '民警签名' }}</h2>
          </div>
          <button :disabled="signingBusy === 'sign'" @click="closeSignature">关闭</button>
        </header>
        <p>签名人：{{ signerName(signatureRole) }}。请在下方区域完成手写签名。</p>
        <canvas
          ref="signatureCanvas"
          class="signature-canvas"
          @pointerdown.prevent="startSignatureStroke"
          @pointermove.prevent="moveSignatureStroke"
          @pointerup.prevent="endSignatureStroke"
          @pointercancel.prevent="endSignatureStroke"
        ></canvas>
        <footer>
          <button :disabled="signingBusy === 'sign'" @click="clearSignature">清空重写</button>
          <button class="primary" :disabled="signingBusy === 'sign'" @click="confirmSignature">{{ signingBusy === 'sign' ? '提交中…' : '确认签名' }}</button>
        </footer>
      </section>
    </div>
  </section>
</template>
