<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { LogOut } from '@lucide/vue'
import { backendErrorMessage, discardAsrFragment, fetchRuntimeCapabilities } from '../api/interrogation'
import { fetchAuthSession } from '../api/officers'
import { fetchSelfServiceState, recordSelfServiceEvent, type SelfServiceState } from '../api/selfService'
import CaseProfilePage from '../components/CaseProfilePage.vue'
import SelfServiceAnswerPage from '../components/SelfServiceAnswerPage.vue'
import SelfServiceIdentityPage from '../components/SelfServiceIdentityPage.vue'
import StepBar from '../components/StepBar.vue'
import TemplatePickerPage from '../components/TemplatePickerPage.vue'
import { useAnswerCapture } from '../composables/answerCapture'
import { TEMPLATE_CATALOG } from '../config/templateCatalog'
import type { FlowStepKey } from '../flow/steps'
import type { RuntimeCapabilities } from '../runtime/types'
import { useInterrogationStore } from '../stores/interrogation'
import { useTemplateInterrogationStore } from '../stores/templateInterrogation'
import { officerDisplayName } from '../utils/officer'
import { SELF_SERVICE_STEPS, firstUnansweredIndex, nextUnansweredIndex, selfServiceQuestions } from '../utils/selfService'
import { sessionStartGuard } from '../utils/sessionStartGuard'

/**
 * 自助模式工作台：民警登录后读卡建档、选好模板，把屏幕交给当事人本人作答。
 *
 *   ①选模板（民警）→ ②建档（本人核对身份）→ ③自助问答（本人逐题口述）
 *   → 结束并交民警定稿：切回人工模式工作台，由民警在③摘入正本、④定稿、⑤签署。
 *
 * 本人的回答只生成待摘入草稿；「以上信息无误」「本题确认无误」「交民警定稿」写入审计留痕。
 * 离开自助模式：正常经民警交回或接管；遇到不可抗力可点左上角「退出」，选择原因后回到大厅，
 * 退出原因与所在步骤写入操作日志，案件保留在台账里，民警之后可从案件记录继续办理。
 */
const props = defineProps<{ caseId: string; startAtTemplate?: boolean }>()
const emit = defineEmits<{ handover: []; exit: [] }>()

const store = useInterrogationStore()
const templateStore = useTemplateInterrogationStore()

type SelfPage = 'template' | 'profile' | 'identity' | 'answer'
// 从大厅新建的自助案件直奔①选模板；首帧就定好，避免先渲染②建档再跳回
const page = ref<SelfPage>(props.startAtTemplate ? 'template' : 'identity')
const selfState = ref<SelfServiceState | null>(null)
const identityChecked = ref(false)
const devices = ref<RuntimeCapabilities | null>(null)
const sessionOfficer = ref<{ name: string; badgeNumber: string } | null>(null)
const current = ref(0)
const busy = ref(false)
const recordingQuestionId = ref<string | null>(null)
const helpOpen = ref(false)
const handoverOpen = ref(false)
const exitOpen = ref(false)
const EXIT_REASONS = ['当事人身体不适', '设备故障', '当事人不愿自助作答', '其他原因'] as const
const exitReason = ref<string>(EXIT_REASONS[0])
const exiting = ref(false)
const exitError = ref('')
let captureTarget: { questionId: string; captureId: string; replace: boolean } | null = null
/** 已交回民警：同一案件马上由人工模式工作台接着用，卸载时不能再清空案件上下文。 */
let handedOver = false

const guard = computed(() => sessionStartGuard(store.caseSummary, devices.value))
const { liveText, beginCapture, finishCapture } = useAnswerCapture(() => guard.value)

const questions = computed(() => selfServiceQuestions(templateStore.workspace.questions, store.facts))
const identityConfirmed = computed(() => Boolean(selfState.value?.identityConfirmedAt))
const confirmedIds = computed(() => selfState.value?.confirmedAnswers.map((item) => item.questionId) ?? [])
const recording = computed(() => Boolean(recordingQuestionId.value) && store.capture.running)

function factValue(key: string) {
  const value = store.facts.find((item) => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : ''
}
const templateTitle = computed(() => TEMPLATE_CATALOG.find((item) => item.backendKey === templateStore.workspace.templateKey)?.title
  || factValue('case_type') || '')
const caseChip = computed(() => [`案 ${store.caseSummary.id || props.caseId}`, templateTitle.value, factValue('interrogation_place')].filter(Boolean).join(' · '))

/** 在场民警：本案询问人优先，其次是当前登录的民警。 */
const officerName = computed(() => {
  const bound = store.caseOfficers.find(Boolean)
  return officerDisplayName(bound?.officerName) || sessionOfficer.value?.name || officerDisplayName(store.caseSummary.officerName)
})
const officerLabel = computed(() => {
  const bound = store.caseOfficers.find(Boolean)
  const badge = bound?.officerId || sessionOfficer.value?.badgeNumber || ''
  return officerName.value ? `民警${officerName.value}${badge ? `（${badge}）` : ''}` : ''
})
const modeText = computed(() => {
  if (page.value === 'template' || page.value === 'profile') return '自助式模式 · 民警建档'
  if (page.value === 'identity') return '自助式模式 · 身份确认'
  return officerName.value ? `自助式模式 · 民警${officerName.value}在场` : '自助式模式 · 民警在场'
})
const micText = computed(() => {
  const state = devices.value?.microphone.state
  if (!state) return ''
  return state === 'AVAILABLE' ? '麦克风在线' : '麦克风未就绪'
})
const blockedReason = computed(() => (recording.value || !devices.value ? '' : guard.value.disabled ? `暂时不能录音：${guard.value.reason.replace(/^完成以下项目后解锁：/, '待完成 ')}，请找在场民警处理` : ''))

const now = ref(new Date())
const clockTimer = window.setInterval(() => { now.value = new Date() }, 30_000)
const clockText = computed(() => {
  const d = now.value
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const stepKey = computed<FlowStepKey>(() => (page.value === 'template' ? 'template' : page.value === 'answer' ? 'dictation' : 'intake'))
const completedSteps = computed<FlowStepKey[]>(() => [
  ...(templateStore.workspace.templateKey ? ['template' as const] : []),
  ...(identityConfirmed.value ? ['intake' as const] : []),
])
/** 本人确认身份后不再回到①选模板；④⑤属于民警，只在交回后进入。 */
const reachableSteps = computed<FlowStepKey[]>(() => (identityConfirmed.value ? ['intake', 'dictation'] : ['template', 'intake']))
const stepHint = computed(() => (page.value === 'answer' ? '转写文字实时上屏 · 确认后进入下一题' : '模板与人工共用 · 身份信息由本人核对确认'))

function selectStep(key: FlowStepKey) {
  if (recording.value || busy.value) return
  if (key === 'template') page.value = 'template'
  else if (key === 'dictation') page.value = 'answer'
  else page.value = 'identity'
}

async function refreshSelfState() {
  const caseId = props.caseId
  try {
    const state = await fetchSelfServiceState(caseId)
    if (props.caseId === caseId) selfState.value = state
  } catch (err) {
    if (props.caseId === caseId) store.feedback(backendErrorMessage(err), true)
  }
}

async function refreshDevices() {
  try {
    devices.value = await fetchRuntimeCapabilities(true)
  } catch (err) {
    devices.value = null
    store.feedback(backendErrorMessage(err), true)
  }
}

watch(() => props.caseId, async (caseId) => {
  page.value = props.startAtTemplate ? 'template' : 'identity'
  selfState.value = null
  void refreshDevices()
  void fetchAuthSession().then((session) => {
    if (session.officer) sessionOfficer.value = { name: session.officer.name, badgeNumber: session.officer.badgeNumber }
  }).catch(() => undefined)
  store.resetCaseContext(caseId)
  templateStore.reset(caseId)
  await store.initialize()
  if (store.caseId !== caseId) return
  try {
    await templateStore.initialize(caseId)
  } catch {
    store.feedback(templateStore.error || '笔录题目加载失败', true)
  }
  await refreshSelfState()
  if (props.caseId !== caseId) return
  identityChecked.value = identityConfirmed.value
  current.value = firstUnansweredIndex(questions.value)
  if (props.startAtTemplate || !templateStore.workspace.templateKey) page.value = 'template'
  else page.value = identityConfirmed.value ? 'answer' : 'identity'
}, { immediate: true })

onUnmounted(() => {
  window.clearInterval(clockTimer)
  // 卸载钩子在下一个页面挂载之后才执行：交回后人工模式工作台已在加载同一案件，这里不能清掉它。
  if (handedOver) return
  if (store.caseId === props.caseId) store.resetCaseContext()
  if (templateStore.caseId === props.caseId) templateStore.reset()
})

async function refreshCase() {
  await store.initialize({ background: true })
  try { await templateStore.initialize(props.caseId) } catch { /* 题目刷新失败不影响补填身份 */ }
}

async function startAnswering() {
  if (busy.value) return
  busy.value = true
  try {
    if (!identityConfirmed.value) selfState.value = await recordSelfServiceEvent(props.caseId, 'IDENTITY_CONFIRM')
    current.value = firstUnansweredIndex(questions.value)
    page.value = 'answer'
  } catch (err) {
    store.feedback(backendErrorMessage(err), true)
  } finally {
    busy.value = false
  }
}

async function startAnswer() {
  const question = questions.value[current.value]
  if (!question || busy.value || captureTarget) return
  busy.value = true
  try {
    recordingQuestionId.value = question.id
    const captureId = await beginCapture()
    if (!captureId) { recordingQuestionId.value = null; return }
    // 已有回答时重说一遍：新的回答替换原草稿，而不是接在后面
    captureTarget = { questionId: question.id, captureId, replace: Boolean(question.answer) }
  } finally {
    busy.value = false
  }
}

function releaseCapture() {
  if (!store.capture.running) { captureTarget = null; recordingQuestionId.value = null }
}

async function stopAnswer() {
  const target = captureTarget
  if (!target || busy.value) return
  busy.value = true
  try {
    const fragments = await finishCapture(target.captureId)
    if (!fragments) return
    if (!fragments.length) { store.feedback('这次没有听清，请靠近话筒再说一遍', true); return }
    await templateStore.attachFragmentAnswer(target.questionId, fragments.map((item) => item.id), { draft: true, replace: target.replace })
    await refreshSelfState()
    store.feedback('已记下，请核对文字是否正确')
  } catch {
    store.feedback(templateStore.error || '回答转写失败，请再说一遍', true)
  } finally {
    releaseCapture()
    busy.value = false
  }
}

/** 重新说一遍：录音中则丢弃这一次录音重新开始；已有回答则重录并替换原草稿。 */
async function redoAnswer() {
  const target = captureTarget
  if (target) {
    if (busy.value) return
    busy.value = true
    try {
      const fragments = await finishCapture(target.captureId)
      if (fragments?.length) await Promise.all(fragments.map((item) => discardAsrFragment(props.caseId, item.id).catch(() => undefined)))
    } finally {
      releaseCapture()
      busy.value = false
    }
    if (captureTarget) return
  }
  await startAnswer()
}

function goNext() {
  const list = questions.value
  if (current.value + 1 < list.length) { current.value += 1; return }
  const next = nextUnansweredIndex(list, current.value)
  if (next >= 0) current.value = next
  else handoverOpen.value = true
}

async function confirmAnswer(questionId: string, value: boolean) {
  try {
    selfState.value = await recordSelfServiceEvent(props.caseId, value ? 'ANSWER_CONFIRM' : 'ANSWER_UNCONFIRM', questionId)
    if (value && questions.value[current.value]?.id === questionId) {
      store.feedback(`第 ${current.value + 1} 题已确认`)
      goNext()
    }
  } catch (err) {
    store.feedback(backendErrorMessage(err), true)
  }
}

async function handOver() {
  if (busy.value || recording.value) return
  busy.value = true
  try {
    await recordSelfServiceEvent(props.caseId, 'HANDOVER')
    handoverOpen.value = false
    helpOpen.value = false
    handedOver = true
    emit('handover')
  } catch (err) {
    store.feedback(backendErrorMessage(err), true)
  } finally {
    busy.value = false
  }
}

function openExit() {
  exitError.value = ''
  helpOpen.value = false
  handoverOpen.value = false
  exitOpen.value = true
}

/** 中途退出：录音中先收尾保留已说的内容，再把原因写入操作日志，回到大厅。 */
async function exitSelfService() {
  if (exiting.value) return
  exiting.value = true
  exitError.value = ''
  try {
    if (captureTarget && !busy.value) await stopAnswer()
    await recordSelfServiceEvent(props.caseId, 'EXIT', undefined, { reason: exitReason.value, step: page.value })
    exitOpen.value = false
    emit('exit')
  } catch (err) {
    exitError.value = `退出未能留痕：${backendErrorMessage(err)}，请重试或请民警处理`
  } finally {
    exiting.value = false
  }
}

const unansweredCount = computed(() => questions.value.filter((item) => !item.answer).length)
</script>

<template>
  <main class="self-workspace">
    <section v-if="store.loading" class="case-loading" aria-live="polite" aria-busy="true">
      <h1>正在加载案件</h1>
      <p>正在读取身份信息与笔录题目…</p>
    </section>

    <template v-else>
      <header class="ss-topbar">
        <button type="button" class="ss-exit" :disabled="exiting" @click="openExit"><LogOut :size="18" aria-hidden="true" />退出</button>
        <span class="ss-topbar-divider" aria-hidden="true"></span>
        <strong>公安笔录一体机</strong>
        <span class="ss-topbar-divider" aria-hidden="true"></span>
        <span class="ss-case-chip">{{ caseChip }}</span>
        <div class="ss-topbar-meta">
          <span class="ss-mode-pill">{{ modeText }}</span>
          <template v-if="page === 'answer' && micText">
            <span class="ss-topbar-divider" aria-hidden="true"></span>
            <span>{{ micText }}</span>
          </template>
          <time>{{ clockText }}</time>
        </div>
      </header>

      <StepBar :steps="SELF_SERVICE_STEPS" :current="stepKey" :completed="completedSteps" :reachable="reachableSteps" @select="selectStep">
        <span class="ss-step-hint">{{ stepHint }}</span>
      </StepBar>

      <div class="ss-toast-region" aria-live="polite">
        <div v-if="store.actionError" class="ss-toast is-error">{{ store.actionError }}</div>
        <div v-else-if="store.actionMessage" class="ss-toast">{{ store.actionMessage }}</div>
      </div>

      <section class="ss-body">
        <TemplatePickerPage
          v-if="page === 'template'"
          :template-key="templateStore.workspace.templateKey ?? null"
          :facts="store.facts"
          :questions="templateStore.workspace.questions"
          @confirm="page = 'identity'"
        />
        <div v-else-if="page === 'profile'" class="ss-profile">
          <p class="ss-profile-note">由在场民警补填或更正身份信息，保存后点「下一步」交回本人核对。</p>
          <CaseProfilePage
            :summary="store.caseSummary"
            :facts="store.facts"
            :reader-available="devices?.identity.state === 'AVAILABLE'"
            @saved="refreshCase"
            @next="page = 'identity'"
          />
        </div>
        <SelfServiceIdentityPage
          v-else-if="page === 'identity'"
          :summary="store.caseSummary"
          :facts="store.facts"
          :officer-name="officerName"
          :case-type="templateTitle"
          :confirmed="identityChecked"
          :busy="busy"
          @confirm="identityChecked = $event"
          @start="startAnswering"
          @fix="page = 'profile'"
          @help="helpOpen = true"
        />
        <SelfServiceAnswerPage
          v-else
          :questions="questions"
          :current="current"
          :recording="recording"
          :busy="busy"
          :live-text="liveText"
          :elapsed-ms="store.captureElapsedMs"
          :confirmed-ids="confirmedIds"
          :officer-label="officerLabel"
          :template-title="templateTitle"
          :blocked-reason="blockedReason"
          @select="current = $event"
          @start="startAnswer"
          @stop="stopAnswer"
          @redo="redoAnswer"
          @skip="goNext"
          @next="goNext"
          @confirm="confirmAnswer"
          @finish="handoverOpen = true"
        />
      </section>
    </template>

    <div v-if="helpOpen || handoverOpen || exitOpen" class="ss-overlay" role="dialog" aria-modal="true" :aria-labelledby="exitOpen ? 'ss-exit-title' : helpOpen ? 'ss-help-title' : 'ss-handover-title'">
      <section v-if="exitOpen" class="ss-dialog">
        <h2 id="ss-exit-title">退出自助模式</h2>
        <p>退出后回到大厅，已说的回答会保留为草稿，案件留在案件记录里，民警可随时继续办理。退出原因会写入操作日志。</p>
        <fieldset class="ss-exit-reasons">
          <legend>退出原因</legend>
          <label v-for="reason in EXIT_REASONS" :key="reason" :class="{ active: exitReason === reason }">
            <input v-model="exitReason" type="radio" name="ss-exit-reason" :value="reason" :disabled="exiting" />{{ reason }}
          </label>
        </fieldset>
        <p v-if="exitError" class="ss-dialog-error" role="alert">{{ exitError }}</p>
        <div class="ss-dialog-actions">
          <button type="button" class="ss-dialog-secondary" :disabled="exiting" @click="exitOpen = false">返回继续</button>
          <button type="button" class="ss-dialog-danger" :disabled="exiting" @click="exitSelfService">{{ exiting ? '正在退出…' : '确认退出' }}</button>
        </div>
      </section>
      <section v-else-if="helpOpen" class="ss-dialog">
        <h2 id="ss-help-title">请稍候，民警马上过来</h2>
        <p>请向在场民警示意。民警可以为您讲解，或接管后改为由民警提问录入（人工模式）。</p>
        <div class="ss-dialog-actions">
          <button type="button" class="ss-dialog-secondary" @click="helpOpen = false">返回继续</button>
          <button type="button" class="ss-dialog-primary" :disabled="busy" @click="handOver">民警接管 · 转人工模式</button>
        </div>
      </section>
      <section v-else class="ss-dialog">
        <h2 id="ss-handover-title">结束作答，交民警定稿</h2>
        <p>交回后本人作答结束，由民警核对每一题并摘入正式笔录。<template v-if="unansweredCount">还有 {{ unansweredCount }} 题没有回答，将标记为「未获取」，民警可在笔录中补充。</template></p>
        <p class="ss-dialog-note">请在场民警到屏幕前确认后再点击交回。</p>
        <div class="ss-dialog-actions">
          <button type="button" class="ss-dialog-secondary" @click="handoverOpen = false">继续作答</button>
          <button type="button" class="ss-dialog-primary" :disabled="busy" @click="handOver">民警已到场，交回定稿</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.self-workspace { display: flex; flex-direction: column; height: 100vh; overflow: hidden; background: var(--surface-sunken); }
.case-loading { display: grid; place-content: center; flex: 1; gap: var(--space-2); color: var(--ink-500); text-align: center; }
.case-loading h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); }

.ss-topbar { display: flex; align-items: center; gap: var(--space-4); flex: 0 0 auto; min-height: var(--height-topbar); padding: 0 var(--space-8); background: var(--navy-900); color: var(--surface); }
.ss-exit { display: inline-flex; align-items: center; gap: var(--space-2); flex: none; min-height: 44px; padding: 0 var(--space-4); border: 1px solid rgba(255, 255, 255, 0.35); border-radius: var(--radius-md); background: transparent; color: var(--surface); font-size: var(--text-md); font-weight: 600; }
.ss-exit:hover:not(:disabled) { background: rgba(255, 255, 255, 0.12); }
.ss-topbar strong { font-size: var(--text-xl); font-weight: 650; letter-spacing: 0.5px; white-space: nowrap; }
.ss-topbar-divider { flex: none; width: 1px; height: 20px; background: rgba(255, 255, 255, 0.22); }
.ss-case-chip { min-width: 0; color: var(--primary-100); font-size: var(--text-md); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ss-topbar-meta { display: flex; align-items: center; gap: var(--space-4); margin-left: auto; color: var(--line-300); font-size: var(--text-sm); white-space: nowrap; }
.ss-topbar-meta time { color: var(--surface); font-size: var(--text-md); font-variant-numeric: tabular-nums; }
.ss-mode-pill { padding: var(--space-2) var(--space-4); border-radius: var(--radius-pill); background: var(--primary-50); color: var(--navy-800); font-size: var(--text-sm); font-weight: 600; }
.ss-step-hint { color: var(--ink-500); font-size: var(--text-sm); }

.ss-toast-region { position: fixed; top: calc(var(--height-topbar) + var(--height-stepbar) + var(--space-3)); left: 50%; z-index: 20; transform: translateX(-50%); pointer-events: none; }
.ss-toast { padding: var(--space-3) var(--space-5); border-radius: var(--radius-md); background: var(--success-100); color: var(--success-700); font-size: var(--text-md); box-shadow: var(--shadow-pop); }
.ss-toast.is-error { background: var(--danger-100); color: var(--danger-700); }

.ss-body { flex: 1 1 auto; min-height: 0; overflow: auto; }
.ss-profile { display: flex; flex-direction: column; }
.ss-profile-note { margin: var(--space-4) var(--space-8) 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-sm); }

.ss-overlay { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--space-5); background: rgba(16, 24, 40, 0.55); }
.ss-dialog { display: flex; flex-direction: column; gap: var(--space-4); width: min(560px, 100%); padding: var(--space-8); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.ss-dialog h2 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 650; }
.ss-dialog p { margin: 0; color: var(--ink-700); font-size: var(--text-md); line-height: 1.6; }
.ss-dialog .ss-dialog-note { color: var(--warning-700); font-size: var(--text-sm); }
.ss-dialog-actions { display: flex; justify-content: flex-end; gap: var(--space-3); margin-top: var(--space-2); }
.ss-dialog-primary, .ss-dialog-secondary, .ss-dialog-danger { min-height: 52px; padding: 0 var(--space-6); border-radius: var(--radius-md); font-size: var(--text-md); font-weight: 600; }
.ss-dialog-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.ss-dialog-primary:disabled { opacity: 0.6; }
.ss-dialog-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.ss-dialog-danger { border: 0; background: var(--danger-600); color: var(--surface); }
.ss-dialog-danger:disabled { opacity: 0.6; }
.ss-dialog .ss-dialog-error { color: var(--danger-700); font-size: var(--text-sm); }
.ss-exit-reasons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); margin: 0; padding: 0; border: 0; }
.ss-exit-reasons legend { margin-bottom: var(--space-2); color: var(--ink-500); font-size: var(--text-sm); }
.ss-exit-reasons label { display: flex; align-items: center; gap: var(--space-3); min-height: 52px; padding: 0 var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-md); color: var(--ink-900); font-size: var(--text-md); cursor: pointer; }
.ss-exit-reasons label.active { border-color: var(--primary-600); background: var(--primary-50); }
.ss-exit-reasons input { width: 20px; height: 20px; accent-color: var(--primary-600); }
</style>
