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
  VoiceprintReadiness,
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
import FormalTemplatePanel from './FormalTemplatePanel.vue'
import LiveDialoguePanel from './LiveDialoguePanel.vue'
import QuestionPreparationPanel from './QuestionPreparationPanel.vue'
import DraftQuestionRail from './DraftQuestionRail.vue'
import RecordArchivePage from './RecordArchivePage.vue'
import RecordReviewPanel from './RecordReviewPanel.vue'
import ReviewChecklistPanel from './ReviewChecklistPanel.vue'
import RecordSigningPage from './RecordSigningPage.vue'
import type { RecordMode } from '../flow/steps'
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
  readiness: VoiceprintReadiness
  completionMode: RecordMode
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
}>()

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
const freezeChecks = ref([false, false, false, false, false])
let signingRequest = 0
const reviewFragments = computed(() => orderedReviewFragments(props.dialogueHistory, false))
const unresolvedFragments = computed(() => reviewFragments.value.filter(item => item.state !== 'CONFIRMED' || !item.confirmedMessageId).length)
const unresolvedQa = computed(() => props.workspace.qaUnits.filter(item => ['OPEN', 'CLOSED', 'ROUTING', 'NEEDS_REVIEW'].includes(item.status)).length)
const completionBusy = computed(() => props.templateBusy || props.captureBusy || reviewBusy.value || !!signingBusy.value)
const freezeReason = computed(() => freezeBlockReason({
  sessionStatus: props.session.status, captureRunning: props.capture.running, busy: completionBusy.value,
  loading: signingLoading.value, loadError: signingLoadError.value, frozen: documentFrozen.value,
  checks: freezeChecks.value, unresolvedFragments: unresolvedFragments.value, unresolvedQa: unresolvedQa.value,
  recordError: props.templateError || (props.workspace.caseId !== props.caseId ? '笔录尚未读取' : ''), hasQuestions: props.workspace.questions.length > 0,
  asrStatus: props.capture.asrStatus, speakerStatus: props.capture.speakerStatus, recordingStatus: props.capture.recordingStatus,
}))
const signatureRole = ref<DocumentSignerRole | null>(null)
const signatureCanvas = ref<HTMLCanvasElement | null>(null)
const signatureStrokes = ref<SignaturePoint[][]>([])
let activeStroke: SignaturePoint[] | null = null

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
    freezeChecks.value = [false, false, false, false, false]
    mode.value = props.session.status === 'COMPLETED' ? 'review' : 'interrogation'
    void loadSigningState()
  },
  { immediate: true },
)
watch(() => props.session.status, (status) => {
  if (status === 'COMPLETED' && mode.value === 'interrogation') mode.value = 'review'
})
// A changed record must be inspected again before the operator freezes it.
watch(() => JSON.stringify([props.summary, props.facts, props.workspace.questions, props.workspace.rounds, props.dialogueHistory, props.workspace.qaUnits]), () => {
  freezeChecks.value = [false, false, false, false, false]
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

function updateFreezeCheck(index: number, checked: boolean) {
  if (index < 0 || index >= 5 || documentFrozen.value || completionBusy.value) return
  freezeChecks.value[index] = checked
}

function toggleCapture() {
  if (documentFrozen.value) {
    signingError.value = '笔录已经冻结，不能继续录音。'
    return
  }
  if (props.capture.running) emit('captureStop', undefined)
  else emit('captureStart')
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
  ctx.strokeStyle = '#111827'
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

function forwardQuestionUpdate(questionId: string, input: CaseQuestionUpdateInput) {
  emit('updateQuestion', questionId, input)
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
    <header v-if="mode !== 'interrogation'" class="record-completion-heading record-no-print"><h1>{{ mode === 'review' ? '定稿校验' : '签署归档' }} · {{ documentFrozen ? documentLocked ? '签署完成' : '已冻结' : session.status === 'COMPLETED' ? '审讯已结束' : '待冻结' }}</h1><p>{{ summary.id }} · {{ summary.suspectName || '姓名未填写' }} · 待确认转写 {{ unresolvedFragments }} 条 · 待处理问答 {{ unresolvedQa }} 组</p></header>

    <RecordSigningPage
      v-if="mode === 'sign'"
      :summary="summary"
      :facts="facts"
      :session="session"
      :questions="workspace.questions"
      :signing-state="signingState"
      :busy="completionBusy || signingLoading"
      :archiving="archiving"
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
      :archived-at="signingState?.createdAt"
      @print="emit('print')"
      @back="emit('back')"
    />

    <div v-else class="template-interrogation-grid" :class="{ 'record-review-grid': mode === 'review', 'draft-first': mode === 'interrogation' }">
      <div class="formal-column">
        <header v-if="mode === 'review'" class="review-formal-heading record-no-print"><strong>询问笔录 · 复核中</strong><span>修改内容离开输入框后保存</span></header>

        <FormalTemplatePanel
          :summary="summary"
          :facts="facts"
          :session="session"
          :questions="workspace.questions"
          :rounds="workspace.rounds"
          :busy="templateBusy || reviewBusy || signingLoading || !!signingLoadError"
          :completion-mode="mode === 'review'"
          :document-frozen="documentFrozen"
          :document-locked="documentLocked"
          :signing-state="signingState"
          :signing-busy="signingBusy"
          :capture-running="capture.running"
          @update-question="forwardQuestionUpdate"
          @reorder="emit('reorderQuestions', $event)"
          @remove-question="(id) => emit('removeQuestion', id)"
          @insert-pending="(pendingId, afterQuestionId) => emit('resolvePending', pendingId, { action: 'ADD', afterQuestionId })"
          @resolve-qa-unit="(qaUnitId, resolution) => emit('resolveQaUnit', qaUnitId, resolution)"
          @update-answer="(id, text) => emit('updateAnswer', id, text)"
          @attach-fragment-answer="(questionId, fragmentIds) => emit('attachFragmentAnswer', questionId, fragmentIds)"
          @create-live-question-from-fragments="(fragmentIds, afterQuestionId) => emit('createLiveQuestionFromFragments', fragmentIds, afterQuestionId)"
          @print="emit('print')"
          @save-library="emit('saveLibrary', $event)"
          @freeze="mode = 'sign'"
          @sign="openSignature"
          @update-header="(target, key, value) => emit('updateHeader', target, key, value)"
        />
      </div>

      <div v-if="mode === 'review'" class="review-side">
        <ReviewChecklistPanel
          :facts="facts"
          :questions="workspace.questions"
          :checks="freezeChecks"
          :block-reason="freezeReason"
          :busy="completionBusy || signingLoading"
          :frozen="documentFrozen"
          :unresolved-fragments="unresolvedFragments"
          :unresolved-qa="unresolvedQa"
          @check="updateFreezeCheck"
          @freeze="finishAndFreeze"
        />
        <details class="raw-transcript review-fragments">
          <summary>待确认转写 {{ unresolvedFragments }} 条 · 待处理问答 {{ unresolvedQa }} 组</summary>
          <RecordReviewPanel :fragments="reviewFragments" :qa-units="workspace.qaUnits" :busy="completionBusy || signingLoading || !!signingLoadError" :frozen="documentFrozen" @confirm="reviewAction($event)" @discard="reviewAction([$event], true)" @resolve-qa-unit="(id, resolution) => emit('resolveQaUnit', id, resolution)" @correct="(id, speaker, reason, text) => emit('correctFragment', id, speaker, reason, text)" />
        </details>
      </div>
      <div v-else class="dialogue-column draft-column">
        <details v-if="session.status === 'READY'" class="record-preparation-drawer draft-preparation record-no-print">
          <summary>问题准备 / 常用问题库</summary>
        <QuestionPreparationPanel
          :library="questionLibrary"
          :busy="templateBusy || reviewBusy || signingLoading || !!signingLoadError"
          :voice-available="questionDictationAvailable"
          :voice-busy="questionDictationActive || questionDictationBusy"
          :voice-draft="questionDictationDraft"
          :voice-error="questionDictationError"
          @load-library="emit('loadLibrary', $event)"
          @add-question="emit('createQuestion', $event)"
          @voice-start="emit('questionDictationStart')"
          @voice-stop="emit('questionDictationStop')"
        />
        </details>

        <DraftQuestionRail
          :questions="workspace.questions"
          :qa-units="workspace.qaUnits"
          :pending-questions="workspace.pendingQuestions"
          :capture-running="capture.running"
          :capture-busy="captureBusy"
          :capture-available="nativeCaptureAvailable && canRecord"
          :locked="documentFrozen || completionBusy"
          @locate="locateQuestion"
          @update-answer="(questionId, text) => emit('updateAnswer', questionId, text)"
          @capture-toggle="toggleCapture"
        />

        <details class="raw-transcript" :open="capture.running">
          <summary>原始转写与说话人识别<small>波形 · 转写 · 说话人 · QA 归档</small></summary>

        <LiveDialoguePanel
          v-if="readiness.suspectReady"
          :case-id="caseId"
          :dialogue="dialogueHistory"
          :fragment-history="fragmentHistory"
          :partial-text="capture.partialText"
          :pending-questions="workspace.pendingQuestions"
          :qa-units="workspace.qaUnits"
          :questions="workspace.questions"
          :suspect-name="summary.suspectName"
          :capture-running="capture.running"
          :capture-status="capture"
          :capture-busy="captureBusy"
          :capture-available="nativeCaptureAvailable && canRecord && !documentFrozen"
          :capture-elapsed-ms="captureElapsedMs"
          @capture-toggle="toggleCapture"
          @resolve-pending="(id, resolution) => emit('resolvePending', id, resolution)"
          @resolve-qa-unit="(id, resolution) => emit('resolveQaUnit', id, resolution)"
          @rollback-qa-unit="(id) => emit('rollbackQaUnit', id)"
          @correct-fragment="(id, speaker, reason) => emit('correctFragment', id, speaker, reason)"
        />
        <div v-else class="dialogue-voiceprint-hint">
          <p>嫌疑人声纹尚未注册。</p>
          <p>请先到「建档 · 声纹注册」完成注册，之后这里才会开始实时语音对话。</p>
        </div>
        </details>
      </div>
    </div>

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
