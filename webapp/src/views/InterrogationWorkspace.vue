<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { backendErrorMessage, fetchRuntimeCapabilities, updateAsrFragment } from '../api/interrogation'
import { updateCaseFact, updateCaseProfile } from '../api/caseProfile'
import {
  startQuestionPreparationDictation,
  stopQuestionPreparationDictation,
} from '../api/templateInterrogation'
import AiSettingsPanel from '../components/AiSettingsPanel.vue'
import CaseProfilePage from '../components/CaseProfilePage.vue'
import CasePreparationPage, { preparationStartGuard } from '../components/CasePreparationPage.vue'
import type { RuntimeCapabilities } from '../runtime/types'
import MossTranscriptionPanel from '../components/MossTranscriptionPanel.vue'
import SessionControls from '../components/SessionControls.vue'
import StepBar from '../components/StepBar.vue'
import TemplateDrivenInterrogationPage from '../components/TemplateDrivenInterrogationPage.vue'
import {
  FLOW_STEPS,
  modeForStep,
  resolveFlowProgress,
  stepIndex,
  stepKeyForMode,
  stepMeta,
  type FlowProgress,
  type FlowStepKey,
  type RecordMode,
} from '../flow/steps'
import VoiceprintAudioSourceBanner from '../components/VoiceprintAudioSourceBanner.vue'
import VoiceprintSetupPage from '../components/VoiceprintSetupPage.vue'
import { useAutoVoiceprintEnrollment } from '../composables/useAutoVoiceprintEnrollment'
import { useInterrogationStore } from '../stores/interrogation'
import { useTemplateInterrogationStore } from '../stores/templateInterrogation'
import type { CaseSummary, TemporaryAsrSpeaker } from '../types/interrogation'
import type {
  CaseQuestionCreateInput,
  CaseQuestionUpdateInput,
  PendingResolution,
  QAUnitResolution,
  RoundReassociateInput,
} from '../types/templateInterrogation'

type WorkspacePage = 'prepare' | 'profile' | 'interrogation' | 'moss' | 'voiceprint'

const props = defineProps<{ caseId: string }>()
defineEmits<{ back: [] }>()
const store = useInterrogationStore()
const templateStore = useTemplateInterrogationStore()
const autoVoiceprint = useAutoVoiceprintEnrollment()
const activePage = ref<WorkspacePage>('prepare')
/** 笔录页的三种形态由步骤条驱动，不再由笔录页内部自建第二套导航 */
const completionMode = ref<RecordMode>('interrogation')
const flowStep = ref<FlowStepKey>('intake')
const INTAKE_PAGES: WorkspacePage[] = ['prepare', 'profile', 'voiceprint']

const flowProgress = computed<FlowProgress>(() => {
  const state = store.caseSummary.workflowState || ''
  const frozen = ['FROZEN', 'SIGNED', 'REPORT_GENERATED'].includes(state)
    || ['FROZEN', 'LOCKED'].includes(store.caseSummary.documentStatus || '')
  return resolveFlowProgress({
    workflowState: state,
    hasTemplate: Boolean(templateStore.workspace.templateKey),
    identityReady: Boolean(store.caseSummary.idNumber),
    voiceprintReady: Boolean(store.voiceprintReadiness?.suspectReady),
    hasQuestions: templateStore.workspace.questions.length > 0,
    frozen,
    signed: ['SIGNED', 'REPORT_GENERATED'].includes(state),
    archived: state === 'REPORT_GENERATED',
  })
})
const currentStepMeta = computed(() => stepMeta(flowStep.value))
const caseTypeText = computed(() => (
  store.caseSummary.caseType === 'suspect_interrogation'
    ? '嫌疑人询问'
    : store.caseSummary.caseType || ''
))

// 推进只向前：数据补齐后自动前进，用户手动回看不会被拽走。
watch(() => flowProgress.value.suggested, (next) => {
  if (stepIndex(next) > stepIndex(flowStep.value)) flowStep.value = next
})

function goStep(key: FlowStepKey, force = false) {
  // 程序化入口（如「进入审讯工作台」）不受步骤门禁限制：
  // 案件可能已有会话，但建档要素仍未补齐。
  if (!force && key !== flowStep.value && !flowProgress.value.reachable.includes(key)) return
  flowStep.value = key
  if (key === 'intake') {
    if (!INTAKE_PAGES.includes(activePage.value)) activePage.value = 'prepare'
    return
  }
  activePage.value = 'interrogation'
  completionMode.value = modeForStep(key)
}

function openIntakePage(page: WorkspacePage) {
  flowStep.value = 'intake'
  activePage.value = page
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
const preparationBusy = ref(false)
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
async function refreshPreparation() {
  if (preparationBusy.value) return
  preparationBusy.value = true
  try { await Promise.all([refreshCaseWorkspace(), checkPreparationDevices()]) }
  finally { preparationBusy.value = false }
}
async function startPreparedSession() {
  if (preparationGuard.value.disabled || preparationBusy.value || questionDictationActive.value || questionDictationBusy.value || store.session.status !== 'READY') return
  preparationBusy.value = true
  try {
    await store.startSession()
    if (['RUNNING'].includes(store.session.status)) openInterrogation()
  } finally { preparationBusy.value = false }
}
const recorderName = computed(() => {
  const recorder = store.officerVoiceprints.find((item) => item.officerId === store.selectedRecorderOfficerId)
  return recorder?.officerName || '未指定'
})

const preparationGuard = computed(() => preparationStartGuard(store.caseSummary, store.voiceprintReadiness, preparationDevices.value, store.voiceprintEnrollmentState))
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
    await autoVoiceprint.dispose()
    if (questionDictationActive.value && previousCaseId && previousCaseId !== nextCaseId) {
      void stopQuestionPreparationDictation(previousCaseId).catch(() => undefined)
    }
    resetQuestionDictationState()
    activePage.value = 'prepare'
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
  },
  { immediate: true },
)

onUnmounted(() => {
  void autoVoiceprint.dispose()
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

function openInterrogation() {
  activePage.value = 'interrogation'
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
    } else {
      await updateCaseFact(caseId, key, {
        value: value || '未录入',
        status: value ? 'confirmed' : 'missing',
      })
    }
    if (store.caseId !== caseId || generation !== recordSaveGeneration) return
    await refreshCaseWorkspace()
    if (store.caseId !== caseId || generation !== recordSaveGeneration) return
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
      store.caseSummary.officerName || '当前警官',
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
      <p>正在读取案件身份、审讯记录、声纹状态等数据…</p>
    </section>

    <template v-else>
      <header class="app-topbar">
        <button type="button" class="topbar-back" @click="$emit('back')">‹ 返回</button>
        <span class="app-brand">笔录智能工作台</span>
        <span class="case-chip">案 {{ store.caseSummary.id || store.caseId }}<template v-if="caseTypeText"> · {{ caseTypeText }}</template></span>

        <div class="app-topbar-meta">
          <span class="topbar-field">询问人 {{ store.caseSummary.officerName || '未指定' }}</span>
          <span class="topbar-divider" aria-hidden="true"></span>
          <span class="topbar-field">记录人 {{ recorderName }}</span>
          <VoiceprintAudioSourceBanner
            class="topbar-audio-source"
            compact
            :source="autoVoiceprint.source.value"
            :reason="autoVoiceprint.reason.value"
            :secure-context="autoVoiceprint.secureContext.value"
          />
          <button type="button" class="topbar-tool" :class="{ active: activePage === 'moss' }" @click="activePage = 'moss'">MOSS 转写</button>
          <AiSettingsPanel />
          <span class="recording" :class="{ muted: store.session.status !== 'RUNNING' }">● {{ store.session.status === 'RUNNING' ? '录制中' : store.session.status === 'PAUSED' ? '已暂停' : '未开始' }}</span>
        </div>
      </header>

      <StepBar
        :steps="FLOW_STEPS"
        :current="flowStep"
        :completed="flowProgress.completed"
        :reachable="flowProgress.reachable"
        @select="goStep"
      >
        <span class="step-hint">{{ currentStepMeta.hint }}</span>
        <template #actions>
          <SessionControls
            v-if="flowStep !== 'intake' && activePage !== 'moss'"
            :session="store.session"
            :start-disabled="preparationGuard.disabled || preparationBusy || questionDictationActive || questionDictationBusy"
            :start-disabled-reason="questionDictationActive || questionDictationBusy ? '请先停止准备阶段语音输入，再开始正式审讯。' : preparationBusy ? '正在处理，请稍候' : preparationGuard.reason"
            @start="startPreparedSession"
            @toggle-pause="store.togglePause"
            @finish="store.finishSession"
            @next-stage="store.nextStage"
          />
          <button v-if="activePage === 'moss'" type="button" class="step-back-tool" @click="goStep('dictation')">回到笔录</button>
        </template>
      </StepBar>

      <nav v-if="flowStep === 'intake' && activePage !== 'moss'" class="intake-subnav" aria-label="建档子步骤">
        <button type="button" :class="{ active: activePage === 'prepare' }" @click="openIntakePage('prepare'); checkPreparationDevices()">询问准备</button>
        <button type="button" :class="{ active: activePage === 'profile' }" @click="openIntakePage('profile')">身份信息</button>
        <button type="button" :class="{ active: activePage === 'voiceprint' }" @click="openIntakePage('voiceprint')">声纹注册</button>
        <span class="intake-hint">核对身份 → 注册声纹 → 设备就绪后可开始正式询问</span>
      </nav>

      <div class="workspace-toast-region" aria-live="polite">
        <div v-if="store.actionError" class="workspace-toast error">{{ store.actionError }}</div>
        <div v-else-if="store.actionMessage" class="workspace-toast success">{{ store.actionMessage }}</div>
      </div>

      <section class="workspace-page-body" :class="{ 'interrogation-workspace-body': activePage === 'interrogation', 'preparation-workspace-body': activePage === 'prepare' || activePage === 'voiceprint' }">
        <CasePreparationPage v-if="activePage === 'prepare'" :summary="store.caseSummary" :facts="store.facts" :readiness="store.voiceprintReadiness" :enrollment-state="store.voiceprintEnrollmentState" :capabilities="preparationDevices" :session-status="store.session.status" :recorder-name="recorderName" :busy="preparationBusy || questionDictationActive || questionDictationBusy" :device-error="preparationDeviceError" @profile="openIntakePage('profile')" @voiceprint="openIntakePage('voiceprint')" @refresh="refreshPreparation" @start="startPreparedSession" @interrogation="goStep('dictation', true)" />
        <CaseProfilePage v-else-if="activePage === 'profile'" :summary="store.caseSummary" :facts="store.facts" @saved="refreshCaseWorkspace" />

        <MossTranscriptionPanel v-else-if="activePage === 'moss'" :case-id="store.caseId || props.caseId" />

        <VoiceprintSetupPage
          v-else-if="activePage === 'voiceprint'"
          :suspect-name="store.caseSummary.suspectName || ''"
          :summary="store.caseSummary"
          :facts="store.facts"
          :recorder-name="recorderName"
          :readiness="store.voiceprintReadiness"
          :officers="store.officerVoiceprints"
          :selected-interrogator-officer-id="store.selectedInterrogatorOfficerId"
          :selected-recorder-officer-id="store.selectedRecorderOfficerId"
          :enrollment-state="store.voiceprintEnrollmentState"
          :busy="store.voiceprintBusy"
          @suspect-start="autoVoiceprint.startSuspect()"
          @suspect-stop="autoVoiceprint.stopSuspect()"
          @select-interrogator="store.selectInterrogatorOfficer($event)"
          @select-recorder="store.selectRecorderOfficer($event)"
          @bind-roles="store.bindVoiceprintRoles()"
          @back="openIntakePage('prepare')"
        />

        <div v-else class="interrogation-workspace-stack">
          <TemplateDrivenInterrogationPage
            :case-id="store.caseId"
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
            :readiness="store.voiceprintReadiness"
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
  gap: var(--space-3);
  flex: 0 0 auto;
  min-height: var(--height-topbar);
  padding: 0 var(--space-6);
  background: var(--navy-900);
  color: var(--surface);
}
.topbar-back {
  min-height: 32px;
  padding: 0 12px 0 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--primary-100);
  font-size: var(--text-sm);
}
.topbar-back:hover { background: rgba(255, 255, 255, 0.1); }
.app-brand { font-size: var(--text-lg); font-weight: 600; letter-spacing: 0.5px; }
.case-chip {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.1);
  color: var(--primary-100);
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 360px;
}
.app-topbar-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-left: auto;
  min-width: 0;
}
.topbar-field { color: var(--line-300); font-size: var(--text-sm); white-space: nowrap; }
.topbar-divider { width: 1px; height: 16px; background: rgba(255, 255, 255, 0.18); }
.topbar-audio-source { border-color: rgba(255, 255, 255, 0.2); background: rgba(255, 255, 255, 0.06); }
.topbar-tool {
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--primary-100);
  font-size: var(--text-sm);
  white-space: nowrap;
}
.topbar-tool:hover { background: rgba(255, 255, 255, 0.12); }
.topbar-tool.active { border-color: var(--primary-600); background: var(--primary-600); color: var(--surface); }
.recording { font-size: var(--text-sm); color: var(--success-600); white-space: nowrap; }
.recording.muted { color: var(--ink-400); }

.step-hint { color: var(--ink-400); font-size: var(--text-sm); }
.step-back-tool {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--line-300);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--primary-600);
  font-size: var(--text-base);
}

.intake-subnav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
  padding: var(--space-2) var(--space-6);
  background: var(--surface);
  border-bottom: 1px solid var(--line-200);
}
.intake-subnav button {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--line-200);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--ink-500);
  font-size: var(--text-base);
}
.intake-subnav button:hover { border-color: var(--primary-200); color: var(--primary-600); }
.intake-subnav button.active {
  border-color: var(--primary-200);
  background: var(--primary-100);
  color: var(--primary-700);
  font-weight: 600;
}
.intake-hint { margin-left: auto; color: var(--ink-300); font-size: var(--text-xs); }

.preparation-workspace-body { padding: 0; overflow: auto; background: var(--surface-sunken); }
.interrogation-workspace-body { padding: 0; overflow: hidden; }
.interrogation-workspace-stack { min-height: 0; height: 100%; }

@media (max-width: 1440px) {
  .topbar-field { display: none; }
  .topbar-divider { display: none; }
}
@media (max-width: 1180px) {
  .case-chip { max-width: 220px; }
  .intake-hint { display: none; }
}
</style>
