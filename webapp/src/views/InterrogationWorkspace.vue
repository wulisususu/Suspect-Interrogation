<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { backendErrorMessage, discardAsrFragment, fetchRuntimeCapabilities, updateAsrFragment } from '../api/interrogation'
import { currentOperatorId } from '../api/operator'
import { updateCaseFact, updateCaseProfile } from '../api/caseProfile'
import {
  startQuestionPreparationDictation,
  stopQuestionPreparationDictation,
} from '../api/templateInterrogation'
import CaseProfilePage from '../components/CaseProfilePage.vue'
import type { RuntimeCapabilities } from '../runtime/types'
import StepBar from '../components/StepBar.vue'
import TemplateDrivenInterrogationPage from '../components/TemplateDrivenInterrogationPage.vue'
import TemplatePickerPage from '../components/TemplatePickerPage.vue'
import {
  FLOW_STEPS,
  modeForStep,
  pageForStep,
  resolveFlowProgress,
  stepIndex,
  stepKeyForMode,
  stepMeta,
  type FlowProgress,
  type FlowStepKey,
  type RecordMode,
  type WorkspacePage,
} from '../flow/steps'
import { TEMPLATE_CATALOG } from '../config/templateCatalog'
import { useInterrogationStore } from '../stores/interrogation'
import { useTemplateInterrogationStore } from '../stores/templateInterrogation'
import { officerDisplayName } from '../utils/officer'
import { sessionStartGuard } from '../utils/sessionStartGuard'
import type { CaseSummary, TemporaryAsrSpeaker } from '../types/interrogation'
import type {
  CaseQuestionCreateInput,
  CaseQuestionUpdateInput,
  PendingResolution,
  QAUnitResolution,
  RoundReassociateInput,
} from '../types/templateInterrogation'

const props = defineProps<{ caseId: string; startAtTemplate?: boolean }>()
defineEmits<{ back: [] }>()
const store = useInterrogationStore()
const templateStore = useTemplateInterrogationStore()
const activePage = ref<WorkspacePage>('profile')
/** 笔录页的三种形态由步骤条驱动，不再由笔录页内部自建第二套导航 */
const completionMode = ref<RecordMode>('interrogation')
const flowStep = ref<FlowStepKey>('intake')

const flowProgress = computed<FlowProgress>(() => {
  const state = store.caseSummary.workflowState || ''
  const frozen = ['FROZEN', 'SIGNED', 'REPORT_GENERATED'].includes(state)
    || ['FROZEN', 'LOCKED'].includes(store.caseSummary.documentStatus || '')
  return resolveFlowProgress({
    workflowState: state,
    hasTemplate: Boolean(templateStore.workspace.templateKey),
    identityReady: Boolean(store.caseSummary.idNumber),
    hasQuestions: templateStore.workspace.questions.length > 0,
    frozen,
    signed: ['SIGNED', 'REPORT_GENERATED'].includes(state),
    archived: state === 'REPORT_GENERATED',
  })
})
const currentStepMeta = computed(() => stepMeta(flowStep.value))
/** ③ 的步骤条右侧按样板显示已选模板，其余步骤显示步骤说明。 */
const stepHint = computed(() => (flowStep.value === 'dictation' && caseTypeText.value
  ? `已选模板：${templateTitle.value || caseTypeText.value}`
  : currentStepMeta.value.hint))
const profileLocked = computed(() => ['FROZEN', 'SIGNED', 'REPORT_GENERATED'].includes(store.caseSummary.workflowState || '')
  || ['FROZEN', 'LOCKED'].includes(store.caseSummary.documentStatus || ''))
function factValue(key: string) {
  const value = store.facts.find((item) => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : ''
}
const templateTitle = computed(() => TEMPLATE_CATALOG.find((item) => item.backendKey === templateStore.workspace.templateKey)?.title || '')
const caseTypeText = computed(() => factValue('case_type')
  || (store.caseSummary.caseType === 'suspect_interrogation' ? templateTitle.value || '嫌疑人询问' : store.caseSummary.caseType || ''))
const caseChip = computed(() => [`案 ${store.caseSummary.id || store.caseId}`, caseTypeText.value, factValue('interrogation_place')].filter(Boolean).join(' · '))
const officerText = computed(() => officerDisplayName(store.caseSummary.officerName) || '未指定')
const recorderName = computed(() => factValue('recorder_name') || '未指定')
const archived = computed(() => store.caseSummary.workflowState === 'REPORT_GENERATED')

/** 顶栏右侧的办理状态（样板各页顶栏）。 */
const statusText = computed(() => {
  const step = flowStep.value
  if (step === 'template') return '新案建立 · 待选模板'
  if (step === 'intake') return flowProgress.value.completed.includes('intake') ? '建档完成 · 可开始询问' : '建档中 · 待补全信息'
  if (step === 'dictation') {
    if (store.session.status === 'RUNNING') return store.capture.running ? '● 已联网 · 实时转写中' : '● 已联网 · 询问进行中'
    if (store.session.status === 'PAUSED') return '询问已暂停'
    return '待开始询问'
  }
  if (step === 'review') return '校验中 · 待确认定稿'
  return archived.value ? '已归档 · 可导出' : '签署中 · 待签名捺印'
})

const now = ref(new Date())
const clockTimer = window.setInterval(() => { now.value = new Date() }, 30_000)
const clockText = computed(() => {
  const d = now.value
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

// 推进只向前：数据补齐后自动前进，用户手动回看不会被拽走。
// 只在同一页面内推进（笔录页的③→④→⑤），步骤条与页面主体始终一致；
// 例如建档页暂存后不会被切到问答页。跨页落点在案件加载完成时一次性决定。
watch(() => flowProgress.value.suggested, (next) => {
  if (stepIndex(next) > stepIndex(flowStep.value) && pageForStep(next) === activePage.value) goStep(next, true)
})

function goStep(key: FlowStepKey, force = false) {
  // 程序化入口（如「进入审讯工作台」）不受步骤门禁限制：
  // 案件可能已有会话，但建档要素仍未补齐。
  if (!force && key !== flowStep.value && !flowProgress.value.reachable.includes(key)) return
  flowStep.value = key
  activePage.value = pageForStep(key)
  if (activePage.value === 'interrogation') completionMode.value = modeForStep(key, archived.value)
}

function onCompletionModeChange(mode: RecordMode) {
  completionMode.value = mode
  flowStep.value = stepKeyForMode(mode)
  if (activePage.value !== 'interrogation') activePage.value = 'interrogation'
}

const recordSavingCount = ref(0)
let recordSaveGeneration = 0
const preparationDevices = ref<RuntimeCapabilities | null>(null)
const preparationDeviceError = ref('')
async function checkPreparationDevices() {
  const caseId = props.caseId
  preparationDeviceError.value = ''
  try {
    const capabilities = await fetchRuntimeCapabilities(true)
    if (props.caseId === caseId) preparationDevices.value = capabilities
  } catch (cause) {
    if (props.caseId !== caseId) return
    preparationDevices.value = null
    preparationDeviceError.value = backendErrorMessage(cause)
  }
}
const preparationGuard = computed(() => sessionStartGuard(store.caseSummary, preparationDevices.value))

/**
 * 逐题录音（样板 P07 交互状态 B）：点卡即录，结束并转写后把这一次录音的片段
 * 挂成该题的待摘入草稿；按住「追加一问」说完即成卡。录音按题归属，不依赖说话人识别。
 */
const answeringQuestionId = ref<string | null>(null)
const questionHoldActive = ref(false)
let answerTarget: { questionId: string; captureId: string; replace: boolean } | null = null
let questionHold: { afterQuestionId: string | null; captureId: string } | null = null

const liveCaptureText = computed(() => {
  const captureId = store.capture.captureSessionId
  if (!store.capture.running || !captureId) return ''
  const finals = templateStore.dialogueHistory
    .filter((item) => item.captureSessionId === captureId && !['DISCARDED', 'SUPERSEDED'].includes(item.state))
    .map((item) => (item.editedText || item.rawText).trim())
  return [...finals, store.capture.partialText?.trim() || ''].filter(Boolean).join('')
})

async function ensureSessionRunning(): Promise<boolean> {
  if (store.session.status === 'RUNNING') return true
  if (store.session.status !== 'READY') {
    store.feedback(store.session.status === 'PAUSED' ? '询问已暂停，请先继续询问' : '本次询问已结束，不能继续录音', true)
    return false
  }
  if (preparationGuard.value.disabled) {
    store.feedback(preparationGuard.value.reason, true)
    return false
  }
  await store.startSession()
  // startSession 会替换 session；TS 仍按进入时的 READY 收窄，这里重新读取。
  const started: string = store.session.status
  return started === 'RUNNING'
}

async function beginCapture(): Promise<string | null> {
  if (store.capture.running || store.captureBusy) return null
  if (!(await ensureSessionRunning())) return null
  await store.startCapture()
  return store.capture.running ? store.capture.captureSessionId || null : null
}

/** 停止录音并取回这一次录音的全部最终片段（停止后重新读取，避免漏掉收尾片段）。 */
async function finishCapture(captureId: string) {
  if (!(await store.stopCapture(undefined, false))) return null
  const caseId = store.caseId
  if (!caseId) return null
  await templateStore.initialize(caseId)
  return templateStore.dialogueHistory
    .filter((item) => item.captureSessionId === captureId && !['DISCARDED', 'SUPERSEDED'].includes(item.state) && (item.editedText || item.rawText).trim())
    .sort((a, b) => a.startedAtMs - b.startedAtMs || a.ordinal - b.ordinal)
}

async function startCardAnswer(questionId: string, replace: boolean) {
  if (answerTarget || questionHold) return
  answeringQuestionId.value = questionId
  const captureId = await beginCapture()
  if (!captureId) { answeringQuestionId.value = null; return }
  answerTarget = { questionId, captureId, replace }
}

async function stopCardAnswer() {
  const target = answerTarget
  if (!target) return
  try {
    const fragments = await finishCapture(target.captureId)
    if (!fragments) return
    if (!fragments.length) { store.feedback('这次没有识别到语音，请靠近话筒重新回答', true); return }
    await templateStore.attachFragmentAnswer(target.questionId, fragments.map((item) => item.id), { draft: true, replace: target.replace })
    store.feedback('已转写为待摘入，核对后点「摘入正本」')
  } catch {
    store.feedback(templateStore.error || '回答转写失败', true)
  } finally {
    if (!store.capture.running) { answerTarget = null; answeringQuestionId.value = null }
  }
}

async function startQuestionHold(afterQuestionId: string | null) {
  if (answerTarget || questionHold) return
  questionHoldActive.value = true
  const captureId = await beginCapture()
  if (!captureId) { questionHoldActive.value = false; return }
  questionHold = { afterQuestionId, captureId }
}

async function stopQuestionHold() {
  const hold = questionHold
  if (!hold) { questionHoldActive.value = false; return }
  try {
    const fragments = await finishCapture(hold.captureId)
    if (!fragments) return
    const text = fragments.map((item) => (item.editedText || item.rawText).trim()).join('')
    if (!text) { store.feedback('没有听清问题，请按住再说一遍，或改为手动输入', true); return }
    await templateStore.createCaseQuestion({ text, source: 'LIVE', afterQuestionId: hold.afterQuestionId })
    // 问题文字已成卡，原始片段丢弃留痕，不再挡住定稿冻结。
    const caseId = store.caseId
    if (caseId) await Promise.all(fragments.map((item) => discardAsrFragment(caseId, item.id).catch(() => undefined)))
    store.feedback('已追加一问')
  } catch {
    store.feedback(templateStore.error || '追加问题失败', true)
  } finally {
    if (!store.capture.running) { questionHold = null; questionHoldActive.value = false }
  }
}
const questionDictationDraft = ref('')
const questionDictationActive = ref(false)
const questionDictationBusy = ref(false)
const questionDictationError = ref('')

function resetQuestionDictationState() {
  questionDictationDraft.value = ''
  questionDictationActive.value = false
  questionDictationBusy.value = false
  questionDictationError.value = ''
}

watch(
  () => props.caseId,
  async (nextCaseId) => {
    recordSaveGeneration += 1
    recordSavingCount.value = 0
    const previousCaseId = store.caseId
    if (questionDictationActive.value && previousCaseId && previousCaseId !== nextCaseId) {
      void stopQuestionPreparationDictation(previousCaseId).catch(() => undefined)
    }
    resetQuestionDictationState()
    activePage.value = 'profile'
    flowStep.value = 'intake'
    preparationDevices.value = null
    void checkPreparationDevices()
    store.resetCaseContext(nextCaseId)
    templateStore.reset(nextCaseId)
    await store.initialize()
    if (store.caseId !== nextCaseId) return
    try {
      await templateStore.initialize(nextCaseId)
    } catch {
      store.feedback(templateStore.error || '模板笔录工作台加载失败', true)
    }
    if (store.caseId === nextCaseId) goStep(props.startAtTemplate ? 'template' : flowProgress.value.suggested, true)
  },
  { immediate: true },
)

onUnmounted(() => {
  window.clearInterval(clockTimer)
  if (questionDictationActive.value && store.caseId) void stopQuestionPreparationDictation(store.caseId).catch(() => undefined)
  if (store.caseId === props.caseId) store.resetCaseContext()
  if (templateStore.caseId === props.caseId) templateStore.reset()
})

async function startQuestionDictation() {
  if (!store.caseId || questionDictationBusy.value || questionDictationActive.value) return
  const caseId = store.caseId
  questionDictationBusy.value = true
  questionDictationError.value = ''
  try {
    const status = await startQuestionPreparationDictation(caseId)
    if (store.caseId !== caseId) return
    questionDictationDraft.value = ''
    questionDictationActive.value = status.active
  } catch (err) {
    if (store.caseId !== caseId) return
    questionDictationError.value = backendErrorMessage(err)
    store.feedback(questionDictationError.value, true)
  } finally {
    if (store.caseId === caseId) questionDictationBusy.value = false
  }
}

async function stopQuestionDictation() {
  if (!store.caseId || questionDictationBusy.value || !questionDictationActive.value) return
  const caseId = store.caseId
  questionDictationBusy.value = true
  questionDictationError.value = ''
  try {
    const status = await stopQuestionPreparationDictation(caseId)
    if (store.caseId !== caseId) return
    questionDictationActive.value = false
    questionDictationDraft.value = status.text || ''
    if (status.lastError) {
      questionDictationError.value = status.lastError
      store.feedback(status.lastError, true)
    }
  } catch (err) {
    if (store.caseId !== caseId) return
    questionDictationError.value = backendErrorMessage(err)
    store.feedback(questionDictationError.value, true)
  } finally {
    if (store.caseId === caseId) questionDictationBusy.value = false
  }
}

async function refreshCaseWorkspace() {
  await store.initialize()
  if (!store.caseId) return
  try {
    await templateStore.initialize(store.caseId)
  } catch {
    store.feedback(templateStore.error || '模板笔录工作台刷新失败', true)
  }
}


async function runTemplateAction(action: () => Promise<unknown>) {
  try { await action() }
  catch { store.feedback(templateStore.error || '模板笔录操作失败', true) }
}

function loadQuestionLibrary(category?: string) { return runTemplateAction(() => templateStore.loadQuestionLibrary(category)) }
function createFormalQuestion(input: CaseQuestionCreateInput) { return runTemplateAction(() => templateStore.createCaseQuestion(input)) }
function updateFormalQuestion(questionId: string, input: CaseQuestionUpdateInput) { return runTemplateAction(() => templateStore.updateCaseQuestion(questionId, input)) }
function reorderFormalQuestions(questionIds: string[]) { return runTemplateAction(() => templateStore.reorderCaseQuestions(questionIds)) }
function resolvePendingQuestion(pendingId: string, resolution: PendingResolution) { return runTemplateAction(() => templateStore.resolvePendingQuestion(pendingId, resolution)) }
function resolveQaUnit(qaUnitId: string, resolution: QAUnitResolution) { return runTemplateAction(() => templateStore.resolveQaUnit(qaUnitId, resolution)) }
function rollbackQaUnit(qaUnitId: string) { return runTemplateAction(() => templateStore.rollbackQaUnit(qaUnitId)) }
function reassociateFormalRound(roundId: string, input: RoundReassociateInput) { return runTemplateAction(() => templateStore.reassociateRound(roundId, input)) }
function updateFormalAnswer(roundId: string, answerText: string) { return runTemplateAction(() => templateStore.updateRoundAnswer(roundId, answerText)) }
function attachFormalFragmentAnswer(questionId: string, fragmentIds: string[]) { return runTemplateAction(() => templateStore.attachFragmentAnswer(questionId, fragmentIds)) }
function createLiveQuestionFromFragments(fragmentIds: string[], afterQuestionId: string | null) { return runTemplateAction(() => templateStore.createLiveQuestionFromFragments(fragmentIds, afterQuestionId)) }
function printFormalRecord() { window.print() }
function saveFormalQuestionToLibrary(questionId: string) { return runTemplateAction(() => templateStore.saveQuestionToLibrary(questionId)) }

async function saveRecordHeader(target: 'case' | 'fact', key: string, value: string) {
  const caseId = store.caseId
  const generation = recordSaveGeneration
  if (!caseId) return
  recordSavingCount.value += 1
  try {
    if (target === 'case') {
      await updateCaseProfile(caseId, { [key]: value } as Partial<CaseSummary>)
      if (store.caseId !== caseId || generation !== recordSaveGeneration) return
      // 抬头只影响本页显示，直接回填本地摘要即可。原先这里走 refreshCaseWorkspace()，
      // 会重新 initialize 整个工作台，页面闪一下、其他输入框里未保存的内容全被冲掉。
      store.caseSummary = { ...store.caseSummary, [key]: value } as CaseSummary
    } else {
      const saved = await updateCaseFact(caseId, key, {
        value: value || '未录入',
        status: value ? 'confirmed' : 'missing',
      })
      if (store.caseId !== caseId || generation !== recordSaveGeneration) return
      const index = store.facts.findIndex((item) => item.key === saved.key)
      if (index >= 0) store.facts[index] = saved
      else store.facts = [...store.facts, saved]
    }
    store.feedback('笔录抬头已保存')
  } catch (err) {
    if (store.caseId === caseId && generation === recordSaveGeneration) store.feedback(backendErrorMessage(err), true)
  } finally {
    if (generation === recordSaveGeneration) recordSavingCount.value -= 1
  }
}

async function correctRecognitionFragment(fragmentId: string, speaker: TemporaryAsrSpeaker, reason: string, text?: string) {
  const caseId = store.caseId
  const generation = recordSaveGeneration
  if (!caseId) return
  const fragment = templateStore.dialogueHistory.find((item) => item.id === fragmentId)
  if (!fragment) {
    store.feedback('未找到需要修正的识别片段，请刷新后重试。', true)
    return
  }
  const cleanReason = reason.trim()
  if (!cleanReason) {
    store.feedback('人工修正必须填写原因。', true)
    return
  }
  recordSavingCount.value += 1
  try {
    await updateAsrFragment(
      caseId,
      fragmentId,
      text ?? (fragment.editedText || fragment.rawText),
      speaker,
      currentOperatorId() ?? (store.caseSummary.officerName || undefined),
      cleanReason,
    )
    if (store.caseId !== caseId || generation !== recordSaveGeneration) return
    await templateStore.initialize(caseId)
    if (store.caseId !== caseId || generation !== recordSaveGeneration) return
    store.feedback('人工修正已保存；原始 AI 识别证据仍独立保留。')
  } catch (err) {
    if (store.caseId !== caseId || generation !== recordSaveGeneration) return
    store.feedback(backendErrorMessage(err), true)
  } finally {
    if (generation === recordSaveGeneration) recordSavingCount.value -= 1
  }
}
</script>

<template>
  <main class="workspace">
    <section v-if="store.loading" class="case-loading" aria-live="polite" aria-busy="true">
      <h1>正在加载案件</h1>
      <p>正在读取案件身份、审讯记录等数据…</p>
    </section>

    <template v-else>
      <header class="app-topbar record-no-print">
        <button type="button" class="app-brand" title="返回案件列表" @click="$emit('back')">笔录智能工作台</button>
        <span class="topbar-divider" aria-hidden="true"></span>
        <span class="case-chip">{{ caseChip }}</span>

        <div class="app-topbar-meta">
          <span class="topbar-field">询问人 {{ officerText }}<i aria-hidden="true">·</i>记录人 {{ recorderName }}</span>
          <span class="topbar-divider" aria-hidden="true"></span>
          <span class="topbar-status" :class="{ live: store.session.status === 'RUNNING' }">{{ statusText }}</span>
          <time class="topbar-clock">{{ clockText }}</time>
        </div>
      </header>

      <StepBar
        class="record-no-print"
        :steps="FLOW_STEPS"
        :current="flowStep"
        :completed="flowProgress.completed"
        :reachable="flowProgress.reachable"
        @select="goStep"
      >
        <span class="step-hint">{{ stepHint }}</span>
      </StepBar>

      <div class="workspace-toast-region record-no-print" aria-live="polite">
        <div v-if="store.actionError" class="workspace-toast error">{{ store.actionError }}</div>
        <div v-else-if="store.actionMessage" class="workspace-toast success">{{ store.actionMessage }}</div>
      </div>

      <section class="workspace-page-body" :class="{ 'interrogation-workspace-body': activePage === 'interrogation', 'preparation-workspace-body': activePage !== 'interrogation' }">
        <TemplatePickerPage
          v-if="activePage === 'template'"
          :template-key="templateStore.workspace.templateKey ?? null"
          :facts="store.facts"
          :questions="templateStore.workspace.questions"
          @confirm="goStep('intake', true)"
        />
        <CaseProfilePage
          v-else-if="activePage === 'profile'"
          :summary="store.caseSummary"
          :facts="store.facts"
          :locked="profileLocked"
          :reader-available="preparationDevices?.identity.state === 'AVAILABLE'"
          @saved="refreshCaseWorkspace"
          @next="goStep('dictation', true)"
        />

        <div v-else class="interrogation-workspace-stack">
          <TemplateDrivenInterrogationPage
            :case-id="store.caseId"
            :officers="store.caseOfficers"
            :summary="store.caseSummary"
            :facts="store.facts"
            :session="store.session"
            :capture="store.capture"
            :can-record="store.canRecord"
            :native-capture-available="store.nativeCaptureAvailable"
            :capture-busy="store.captureBusy"
            :capture-elapsed-ms="store.captureElapsedMs"
            :workspace="templateStore.workspace"
            :dialogue-history="templateStore.dialogueHistory"
            :fragment-history="store.fragmentHistory"
            :question-library="templateStore.questionLibrary"
            :template-busy="templateStore.loading || templateStore.mutating || recordSavingCount > 0"
            :template-error="templateStore.error"
            :question-dictation-available="store.nativeCaptureAvailable && store.session.status === 'READY'"
            :question-dictation-active="questionDictationActive"
            :question-dictation-busy="questionDictationBusy"
            :question-dictation-draft="questionDictationDraft"
            :question-dictation-error="questionDictationError"
            :recorder-name="recorderName === '未指定' ? '' : recorderName"
            :recording-question-id="answeringQuestionId"
            :question-recording="questionHoldActive"
            :live-text="liveCaptureText"
            :completion-mode="completionMode"
            @update:completion-mode="onCompletionModeChange"
            @saved="refreshCaseWorkspace"
            @capture-start="store.startCapture"
            @capture-stop="store.stopCapture($event)"
            @question-dictation-start="startQuestionDictation"
            @question-dictation-stop="stopQuestionDictation"
            @load-library="loadQuestionLibrary"
            @create-question="createFormalQuestion"
            @update-question="updateFormalQuestion"
            @reorder-questions="reorderFormalQuestions"
            @resolve-pending="resolvePendingQuestion"
            @resolve-qa-unit="resolveQaUnit"
            @rollback-qa-unit="rollbackQaUnit"
            @reassociate-round="reassociateFormalRound"
            @update-answer="updateFormalAnswer"
            @attach-fragment-answer="attachFormalFragmentAnswer"
            @create-live-question-from-fragments="createLiveQuestionFromFragments"
            @print="printFormalRecord"
            @save-library="saveFormalQuestionToLibrary"
            @correct-fragment="correctRecognitionFragment"
            @update-header="saveRecordHeader"
            @back="$emit('back')"
            @answer-start="startCardAnswer"
            @answer-stop="stopCardAnswer"
            @question-hold-start="startQuestionHold"
            @question-hold-end="stopQuestionHold"
            @toggle-pause="store.togglePause"
          />
        </div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.app-topbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex: 0 0 auto;
  min-height: 64px;
  padding: 0 var(--space-8);
  background: var(--navy-900);
  color: var(--surface);
}
.app-brand {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--surface);
  font-size: var(--text-xl);
  font-weight: 650;
  letter-spacing: 0.5px;
  white-space: nowrap;
}
.app-brand:hover { color: var(--primary-100); }
.case-chip {
  color: var(--primary-100);
  font-size: var(--text-md);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.app-topbar-meta {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-left: auto;
  min-width: 0;
  color: var(--line-300);
  font-size: var(--text-sm);
  white-space: nowrap;
}
.topbar-field i { margin: 0 var(--space-2); font-style: normal; }
.topbar-divider { flex: none; width: 1px; height: 20px; background: rgba(255, 255, 255, 0.22); }
.topbar-status.live { color: var(--success-100); }
.topbar-clock { color: var(--surface); font-size: var(--text-md); font-variant-numeric: tabular-nums; }

.step-hint { color: var(--ink-500); font-size: var(--text-sm); }

.preparation-workspace-body { padding: 0; overflow: auto; background: var(--surface-sunken); }
.interrogation-workspace-body { padding: 0; overflow: hidden; }
.interrogation-workspace-stack { min-height: 0; height: 100%; }

@media (max-width: 1440px) {
  .topbar-field { display: none; }
  .topbar-field + .topbar-divider { display: none; }
}
</style>
