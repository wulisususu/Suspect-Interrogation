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
import TemplateDrivenInterrogationPage from '../components/TemplateDrivenInterrogationPage.vue'
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
      <header class="topbar">
        <button class="back-btn" @click="$emit('back')">‹ 返回</button>
        <h1>案件审讯工作台</h1>
        <span class="topbar-field">案件：{{ store.caseSummary.id || store.caseId }}</span>
        <span class="topbar-field">嫌疑人：{{ store.caseSummary.suspectName || '待录入' }}</span>
        <span class="topbar-field">主审：{{ store.caseSummary.officerName || '当前警官' }}</span>
        <span class="topbar-field">记录员：{{ recorderName }}</span>
        <AiSettingsPanel />
        <VoiceprintAudioSourceBanner
          class="topbar-audio-source"
          compact
          :source="autoVoiceprint.source.value"
          :reason="autoVoiceprint.reason.value"
          :secure-context="autoVoiceprint.secureContext.value"
        />
        <span class="recording" :class="{ muted: store.session.status !== 'RUNNING' }">● {{ store.session.status === 'RUNNING' ? '审讯中' : store.session.status === 'PAUSED' ? '已暂停' : '未录入' }}</span>
      </header>

      <nav class="workspace-page-tabs" aria-label="案件工作区页面">
        <button :class="{ active: activePage === 'prepare' }" @click="activePage = 'prepare'; checkPreparationDevices()"><b>1</b><span>询问准备</span></button>
        <button :class="{ active: activePage === 'profile' }" @click="activePage = 'profile'">
          <b>A</b><span>身份信息</span>
        </button>
        <button :class="{ active: activePage === 'voiceprint' }" @click="activePage = 'voiceprint'">
          <b>B</b><span>声纹注册</span>
        </button>
        <button :class="{ active: activePage === 'interrogation' }" @click="openInterrogation">
          <b>C</b><span>审讯记录</span>
        </button>
        <button :class="{ active: activePage === 'moss' }" @click="activePage = 'moss'">
          <b>D</b><span>MOSS 转写</span>
        </button>
        <SessionControls
          v-if="activePage !== 'prepare' && activePage !== 'voiceprint'"
          :session="store.session"
          :start-disabled="preparationGuard.disabled || preparationBusy || questionDictationActive || questionDictationBusy"
          :start-disabled-reason="questionDictationActive || questionDictationBusy ? '请先停止准备阶段语音输入，再开始正式审讯。' : preparationBusy ? '正在处理，请稍候' : preparationGuard.reason"
          @start="startPreparedSession"
          @toggle-pause="store.togglePause"
          @finish="store.finishSession"
          @next-stage="store.nextStage"
        />
      </nav>

      <div class="workspace-toast-region" aria-live="polite">
        <div v-if="store.actionError" class="workspace-toast error">{{ store.actionError }}</div>
        <div v-else-if="store.actionMessage" class="workspace-toast success">{{ store.actionMessage }}</div>
      </div>

      <section class="workspace-page-body" :class="{ 'interrogation-workspace-body': activePage === 'interrogation', 'preparation-workspace-body': activePage === 'prepare' || activePage === 'voiceprint' }">
        <CasePreparationPage v-if="activePage === 'prepare'" :summary="store.caseSummary" :facts="store.facts" :readiness="store.voiceprintReadiness" :enrollment-state="store.voiceprintEnrollmentState" :capabilities="preparationDevices" :session-status="store.session.status" :recorder-name="recorderName" :busy="preparationBusy || questionDictationActive || questionDictationBusy" :device-error="preparationDeviceError" @profile="activePage = 'profile'" @voiceprint="activePage = 'voiceprint'" @refresh="refreshPreparation" @start="startPreparedSession" @interrogation="openInterrogation" />
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
          @back="activePage = 'prepare'; checkPreparationDevices()"
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
          />
        </div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.preparation-workspace-body { padding: 0; overflow: auto; background: #f4f6fb; }
.topbar { min-height: 60px; padding: 12px 24px; gap: 16px; background: #19345e; flex-wrap: wrap; }
.topbar h1 { font-size: 18px; }
.topbar-field { font-size: 13px; }
.workspace-page-tabs { padding: 0 24px; min-height: 46px; }
.workspace-page-tabs > button { min-width: 130px; font-size: 14px; }
.interrogation-workspace-body { padding: 0; overflow: hidden; }
.interrogation-workspace-stack {
  min-height: 0;
  height: 100%;
}
</style>
