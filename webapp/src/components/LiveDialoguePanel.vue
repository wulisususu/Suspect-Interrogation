<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import type { AsrCaptureStatus, TemporaryAsrFragment, TemporaryAsrSpeaker } from '../types/interrogation'
import { judgeDevBotReply, devBotAsk, devBotNextQuestion } from '../api/devBot'
import type {
  FormalQAUnit,
  FormalQuestion,
  PendingFormalQuestion,
  PendingResolution,
  QAUnitResolution,
} from '../types/templateInterrogation'
import { dialoguePresentation, groupLiveDialogueFragments } from '../utils/templateInterrogation'
import { armDrop, clearDrop, pendingDrop } from '../composables/pendingDrop'
import AsrWorkflowStatus from './AsrWorkflowStatus.vue'
import RecorderWaveformCanvas from './RecorderWaveformCanvas.vue'

const props = defineProps<{
  caseId: string
  dialogue: TemporaryAsrFragment[]
  partialText: string
  pendingQuestions: PendingFormalQuestion[]
  qaUnits: FormalQAUnit[]
  questions: FormalQuestion[]
  suspectName?: string
  captureRunning: boolean
  captureStatus: AsrCaptureStatus
  fragmentHistory: (fragmentId: string) => TemporaryAsrFragment[]
  captureBusy: boolean
  captureAvailable: boolean
  captureElapsedMs: number
}>()

const emit = defineEmits<{
  captureToggle: []
  resolvePending: [pendingId: string, resolution: PendingResolution]
  resolveQaUnit: [qaUnitId: string, resolution: QAUnitResolution]
  rollbackQaUnit: [qaUnitId: string]
  correctFragment: [fragmentId: string, speaker: TemporaryAsrSpeaker, reason: string]
}>()

const transcriptFeed = ref<HTMLElement | null>(null)
const pinnedToBottom = ref(true)
const correctionSpeaker = ref<Record<string, TemporaryAsrSpeaker>>({})
const correctionReason = ref<Record<string, string>>({})
const livePreviewUnavailable = computed(() => ['MODEL_NOT_INSTALLED', 'ERROR'].includes(
  String(props.captureStatus.liveTranscriptStatus ?? '').toUpperCase(),
))
const livePreviewUnavailableMessage = computed(() => (
  props.captureStatus.liveTranscriptStatus === 'MODEL_NOT_INSTALLED'
    ? '实时转写模型未安装，最终文字仍会保存'
    : '实时转写暂不可用，最终文字仍会保存'
))
const qaReviewUnits = computed(() => props.qaUnits.filter((unit) => unit.status === 'NEEDS_REVIEW'))
const qaResolvedUnits = computed(() => props.qaUnits.filter((unit) => unit.status === 'APPLIED' || unit.status === 'IGNORED' || unit.status === 'ROLLED_BACK'))
const visibleDialogue = computed(() => groupLiveDialogueFragments([...props.dialogue, ...botTurns.value]))
const recognitionFragments = computed(() => [...props.dialogue]
  .filter((item) => item.state !== 'DISCARDED' && item.state !== 'SUPERSEDED' && (item.editedText || item.rawText).trim())
  .sort((left, right) => left.startedAtMs - right.startedAtMs || left.ordinal - right.ordinal || left.id.localeCompare(right.id)))

// ---------------------------------------------------------------------------
// Dev-only BOT interrogator: one person plays both roles. The bot asks the
// case's formal questions as text; the tester replies by voice through the
// normal ASR capture. A reply counts when no new suspect fragment arrives for
// 10s, then the cloud LLM judges whether it answers the question. This whole
// block is a test rig and must never grow into the production flow.
// ---------------------------------------------------------------------------
const BOT_SILENCE_MS = 20_000
const BOT_MAX_DYNAMIC = 10
const BOT_STORAGE_PREFIX = 'dev-bot-turns:'
let botSeq = 0
let botQueue: FormalQuestion[] = []
let botCurrent: { id: string; text: string } | null = null
let botBaselineIds = new Set<string>()
let botEmptyStreak = 0
let botDynamicCount = 0
let botAskedTexts: string[] = []
let botAnswerTexts: string[] = []
let botSilenceTimer: ReturnType<typeof setTimeout> | undefined
const botActive = ref(false)
const botJudging = ref(false)
const botGenerating = ref(false)
const botTurns = ref<TemporaryAsrFragment[]>([])

const botStorageKey = computed(() => `${BOT_STORAGE_PREFIX}${props.caseId}`)
const botAnsweredKey = computed(() => `dev-bot-answered:${props.caseId}`)
let botAnsweredIds = new Set<string>()

function loadBotAnswered() {
  try {
    const raw = localStorage.getItem(botAnsweredKey.value)
    botAnsweredIds = new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    botAnsweredIds = new Set()
  }
}

function markBotAnswered(questionId: string) {
  botAnsweredIds.add(questionId)
  try {
    localStorage.setItem(botAnsweredKey.value, JSON.stringify([...botAnsweredIds]))
  } catch { /* storage unavailable */ }
}

function isBotFragment(item: TemporaryAsrFragment) {
  return item.id.startsWith('dev-bot-') || item.modelId === 'dev-bot'
}

function botTurnFrom(text: string, createdAt: number, id: string): TemporaryAsrFragment {
  const seq = Number(id.slice('dev-bot-'.length)) || 0
  return {
    id,
    captureSessionId: 'dev-bot',
    caseId: '',
    ordinal: 1_000_000 + seq,
    startedAtMs: createdAt,
    endedAtMs: createdAt,
    rawText: text,
    editedText: '',
    speaker: 'INTERROGATOR',
    speakerId: null,
    speakerName: 'BOT 民警',
    speakerScore: null,
    secondBestScore: null,
    speakerThreshold: null,
    speakerMargin: null,
    speakerSource: 'MANUAL',
    voiceprintVerified: false,
    confidence: null,
    confidenceSource: 'UNAVAILABLE',
    lowConfidence: false,
    state: 'CONFIRMED',
    confirmedQaId: null,
    confirmedMessageId: null,
    recognitionEvidence: null,
    recognitionRevisions: [],
    audio: { captureSessionId: 'dev-bot', startOffsetMs: 0, endOffsetMs: 0, available: false },
    createdAt,
    updatedAt: createdAt,
  }
}

function botTurn(text: string): TemporaryAsrFragment {
  botSeq += 1
  return botTurnFrom(text, Date.now(), `dev-bot-${botSeq}`)
}

function persistBotTurns() {
  try {
    const data = botTurns.value.map((item) => ({ id: item.id, text: item.rawText, createdAt: item.createdAt }))
    localStorage.setItem(botStorageKey.value, JSON.stringify(data.slice(-300)))
  } catch { /* storage unavailable — bot turns stay in-memory only */ }
}

function restoreBotTurns() {
  try {
    const raw = localStorage.getItem(botStorageKey.value)
    if (!raw) return
    const parsed = JSON.parse(raw) as Array<{ id?: unknown; text?: unknown; createdAt?: unknown }>
    if (!Array.isArray(parsed)) return
    let maxSeq = 0
    const restored: TemporaryAsrFragment[] = []
    for (const item of parsed) {
      if (typeof item?.id !== 'string' || typeof item?.text !== 'string' || typeof item?.createdAt !== 'number') continue
      restored.push(botTurnFrom(item.text, item.createdAt, item.id))
      maxSeq = Math.max(maxSeq, Number(item.id.slice('dev-bot-'.length)) || 0)
    }
    botTurns.value = restored
    botSeq = Math.max(botSeq, maxSeq)
  } catch { /* corrupted snapshot — start clean */ }
}

function pushBotTurn(text: string) {
  botTurns.value = [...botTurns.value, botTurn(text)]
  persistBotTurns()
}

function clearBotSilenceTimer() {
  if (botSilenceTimer) clearTimeout(botSilenceTimer)
  botSilenceTimer = undefined
}

function suspectFragmentIds() {
  return new Set(props.dialogue.filter((item) => item.speaker === 'SUSPECT').map((item) => item.id))
}

function armSilenceTimer() {
  clearBotSilenceTimer()
  botSilenceTimer = setTimeout(() => { void onBotSilence() }, BOT_SILENCE_MS)
}

async function toggleBot() {
  if (botActive.value) {
    stopBot()
    return
  }
  if (!props.captureAvailable) {
    pushBotTurn('（BOT）当前录音不可用：请先点「开始审讯」让会话进入审讯中，确认录音可用后再点 BOT。')
    return
  }
  botActive.value = true
  botEmptyStreak = 0
  botDynamicCount = 0
  botAskedTexts = []
  botAnswerTexts = []
  loadBotAnswered()
  // Skip questions already routed into the formal record (rounds) and ones the
  // judge already accepted, so a refresh never re-asks answered questions.
  botQueue = props.questions.filter(
    (item) => item.active && !(item.rounds && item.rounds.length) && !botAnsweredIds.has(item.id),
  )
  if (!props.captureRunning) {
    emit('captureToggle')
    // The REST start is async: wait until the backend capture session really
    // exists before injecting the first question, otherwise the injection is
    // rejected with "no active capture".
    const started = await waitForCaptureRunning(10_000)
    if (!started) {
      pushBotTurn('（BOT）录音未能自动开启，请手动点击「开始录音」后再点 BOT。')
      stopBot()
      return
    }
  }
  await askNextBotQuestion()
}

function waitForCaptureRunning(timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs
    const timer = setInterval(() => {
      if (props.captureRunning || Date.now() > deadline) {
        clearInterval(timer)
        resolve(props.captureRunning)
      }
    }, 300)
  })
}

function stopBot() {
  botActive.value = false
  botCurrent = null
  botGenerating.value = false
  clearBotSilenceTimer()
}

async function askNextBotQuestion() {
  clearBotSilenceTimer()
  const question = botQueue.shift()
  if (!question) {
    await askDynamicQuestion()
    return
  }
  botCurrent = question
  botBaselineIds = suspectFragmentIds()
  // The question is injected as a REAL interrogator fragment so the suspect
  // answer flows through the normal QA-unit / formal-record routing pipeline.
  try {
    await devBotAsk(props.caseId, question.text)
    botAskedTexts.push(question.text)
  } catch (err) {
    pushBotTurn(`（BOT 提问失败：${err instanceof Error ? err.message : '未知错误'}）BOT 已暂停。`)
    stopBot()
    return
  }
  armSilenceTimer()
}

async function askDynamicQuestion() {
  if (!botActive.value) return
  if (botDynamicCount >= BOT_MAX_DYNAMIC) {
    botCurrent = null
    pushBotTurn(`（BOT）动态追问已达测试上限 ${BOT_MAX_DYNAMIC} 条，停止提问。`)
    stopBot()
    return
  }
  botGenerating.value = true
  try {
    const text = await devBotNextQuestion(props.caseId, botAskedTexts, botAnswerTexts)
    if (!botActive.value) return
    botDynamicCount += 1
    botCurrent = { id: `dynamic-${botDynamicCount}`, text }
    botBaselineIds = suspectFragmentIds()
    await devBotAsk(props.caseId, text)
    botAskedTexts.push(text)
  } catch (err) {
    pushBotTurn(`（BOT 生成追问失败：${err instanceof Error ? err.message : '未知错误'}）BOT 已暂停。`)
    stopBot()
    return
  } finally {
    botGenerating.value = false
  }
  armSilenceTimer()
}

async function onBotSilence() {
  const question = botCurrent
  if (!botActive.value || !question) return
  const reply = props.dialogue
    .filter((item) => item.speaker === 'SUSPECT' && !botBaselineIds.has(item.id))
    .map((item) => (item.editedText || item.rawText || '').trim())
    .filter(Boolean)
    .join(' ')
  if (!reply) {
    botEmptyStreak += 1
    if (!props.captureRunning || botEmptyStreak >= 3) {
      pushBotTurn('（BOT）连续 20 秒都没有转写到你的回复，BOT 已暂停。请确认「开始审讯」和录音已开启，再点 BOT 重试。')
      stopBot()
      return
    }
    pushBotTurn('（BOT）20 秒内没有转写到你的回复，请对着麦克风说话。')
    botBaselineIds = suspectFragmentIds()
    armSilenceTimer()
    return
  }
  botEmptyStreak = 0
  botJudging.value = true
  try {
    const verdict = await judgeDevBotReply(question.text, reply)
    if (verdict.isAnswer) {
      markBotAnswered(question.id)
      botAnswerTexts.push(reply)
      botCurrent = null
      askNextBotQuestion()
    } else {
      pushBotTurn(`（BOT 判定：还不算回答）${verdict.comment || '请再说明一下。'}`)
      botBaselineIds = suspectFragmentIds()
      armSilenceTimer()
    }
  } catch (err) {
    pushBotTurn(`（BOT 判定失败：${err instanceof Error ? err.message : '未知错误'}）跳过本题，继续下一题。`)
    botCurrent = null
    askNextBotQuestion()
  } finally {
    botJudging.value = false
  }
}

watch(() => props.dialogue.length, () => {
  if (!botActive.value || !botCurrent) return
  const hasNewSuspectText = props.dialogue.some(
    (item) => item.speaker === 'SUSPECT' && !botBaselineIds.has(item.id) && (item.editedText || item.rawText || '').trim(),
  )
  if (hasNewSuspectText) armSilenceTimer()
})

// While capture runs, the transcription bubble stays mounted (with a 待输入
// placeholder when idle) so the partial text does not flash between utterances.

onUnmounted(() => {
  clearBotSilenceTimer()
})

const elapsed = computed(() => {
  const total = Math.floor(props.captureElapsedMs / 1000)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
})
const audioMeterSamples = computed(() => props.captureStatus.audioLevels?.slice(-240) ?? [])
const audioMeterSignal = computed(() => {
  if (!props.captureRunning) return 'STOPPED'
  if (!audioMeterSamples.value.length) return 'WAITING'
  const updatedAt = props.captureStatus.audioLevelUpdatedAt
  const captureStart = props.captureStatus.startedAt
  const now = captureStart == null ? Date.now() : captureStart + props.captureElapsedMs
  if (updatedAt == null || now - updatedAt > 1500) return 'STALE'
  return 'LIVE'
})

function formatTime(item: TemporaryAsrFragment) {
  if (!item.createdAt) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(item.createdAt))
}

function formatDate(value?: number | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value))
}

function speakerLabel(role?: TemporaryAsrSpeaker | null) {
  if (role === 'SUSPECT') return '嫌疑人'
  if (role === 'INTERROGATOR') return '主审民警'
  if (role === 'RECORDER') return '记录民警'
  if (role === 'OFFICER_FALLBACK') return '非嫌疑人 / 未确认民警'
  return '未知人员'
}

function recognitionNeedsReview(item: TemporaryAsrFragment) {
  return item.speaker === 'UNKNOWN'
    || item.speaker === 'OFFICER_FALLBACK'
    || item.speakerSource === 'PENDING_ANALYSIS'
    || item.lowConfidence
}

function recognitionStatusLabel(item: TemporaryAsrFragment) {
  if (item.speakerSource === 'PENDING_ANALYSIS') return '声纹分析中'
  if (recognitionNeedsReview(item)) return '待人工复核'
  return item.voiceprintVerified ? '声纹已匹配' : '已归属'
}

function speakerName(item: TemporaryAsrFragment) {
  const presentation = dialoguePresentation(item)
  if (item.speaker === 'SUSPECT') return props.suspectName || item.speakerName || presentation.badge
  return item.speakerName || presentation.badge
}

function pendingFor(fragmentId: string) {
  return props.pendingQuestions.find((item) => item.officerFragmentId === fragmentId && (item.status === 'PENDING' || item.status === 'DEFERRED'))
}

function candidateQuestions(pending: PendingFormalQuestion) {
  const ids = new Set(pending.candidateQuestionIds)
  return props.questions.filter((question) => ids.has(question.id))
}

function resolve(pending: PendingFormalQuestion, resolution: PendingResolution) {
  emit('resolvePending', pending.id, resolution)
}

const FORMAL_ANSWER_FRAGMENT_MIME = 'application/x-formal-answer-fragments'

function dialogueDropEntries(fragments: TemporaryAsrFragment[]) {
  const fragmentIds = fragments.filter((item) => !isBotFragment(item)).map((item) => item.id)
  if (!fragmentIds.length) return []
  const text = fragments
    .filter((item) => !isBotFragment(item))
    .map((item) => (item.editedText || item.rawText || '').trim())
    .join('')
  const entries = [
    { mime: FORMAL_ANSWER_FRAGMENT_MIME, data: JSON.stringify({ fragmentIds, text }) },
  ]
  const pending = pendingFor(fragmentIds[0])
  if (pending) {
    entries.push({
      mime: 'application/x-formal-pending-question',
      data: JSON.stringify({ pendingId: pending.id }),
    })
  }
  return entries
}

function startDialogueDrag(event: DragEvent, fragments: TemporaryAsrFragment[]) {
  if (!event.dataTransfer) return
  const entries = dialogueDropEntries(fragments)
  if (!entries.length) return
  event.dataTransfer.effectAllowed = 'copy'
  for (const entry of entries) event.dataTransfer.setData(entry.mime, entry.data)
}

/** 触摸屏点选：等价于「按下了拖动但还没松手」，之后点笔录栏位即放置。 */
function armDialogue(fragments: TemporaryAsrFragment[]) {
  const entries = dialogueDropEntries(fragments)
  if (entries.length) armDrop(entries, '对话片段')
}

function toggleDialogueSelection(fragments: TemporaryAsrFragment[]) {
  if (dialogueArmed(fragments)) {
    clearDrop()
    return
  }
  armDialogue(fragments)
}

function dialogueArmed(fragments: TemporaryAsrFragment[]) {
  const ids = fragments.filter((item) => !isBotFragment(item)).map((item) => item.id)
  const payload = pendingDrop.value
  if (!ids.length || !payload) return false
  return payload.entries.some(
    (entry) => entry.mime === FORMAL_ANSWER_FRAGMENT_MIME && ids.every((id) => entry.data.includes(id)),
  )
}

function wholeQaDropEntries(unit: FormalQAUnit) {
  return [{ mime: 'application/x-formal-qa-unit', data: JSON.stringify({ qaUnitId: unit.id, mode: 'QA' }) }]
}

function answerQaDropEntries(unit: FormalQAUnit) {
  return [{ mime: 'application/x-formal-qa-unit', data: JSON.stringify({ qaUnitId: unit.id, mode: 'ANSWER' }) }]
}

function startQaDrag(event: DragEvent, payload: { qaUnitId: string; mode: 'QA' | 'ANSWER' }) {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-formal-qa-unit', JSON.stringify(payload))
}

function startWholeQaDrag(event: DragEvent, unit: FormalQAUnit) {
  startQaDrag(event, { qaUnitId: unit.id, mode: 'QA' })
}

function startAnswerDrag(event: DragEvent, unit: FormalQAUnit) {
  startQaDrag(event, { qaUnitId: unit.id, mode: 'ANSWER' })
}

function resolveQa(unit: FormalQAUnit, resolution: QAUnitResolution) {
  emit('resolveQaUnit', unit.id, resolution)
}

function rollbackQa(unit: FormalQAUnit) {
  if (unit.status !== 'APPLIED') return
  if (!window.confirm('仅回退本次正式笔录回答，问题和原始对话会保留。确定继续吗？')) return
  emit('rollbackQaUnit', unit.id)
}

function qaStatusLabel(unit: FormalQAUnit) {
  if (unit.status === 'IGNORED' || unit.classification === 'IGNORE') return '已忽略·仅原始对话'
  if (unit.status === 'NEEDS_REVIEW') return '待处理'
  if (unit.status === 'ROLLED_BACK') return '已回退·问题保留'
  if (unit.classification === 'MATCH_FIXED') return '已归档·固定模板'
  if (unit.classification === 'MATCH_EXISTING') return '已归档·已有问题'
  if (unit.classification === 'CREATE_LIVE_FROM_SPEECH') return '已新增·现场问题'
  return unit.status
}

function correctionRole(item: TemporaryAsrFragment): TemporaryAsrSpeaker {
  return correctionSpeaker.value[item.id] || item.speaker
}

function submitCorrection(item: TemporaryAsrFragment) {
  const reason = (correctionReason.value[item.id] || '').trim()
  if (!reason) return
  emit('correctFragment', item.id, correctionRole(item), reason)
}

function onFeedScroll() {
  const element = transcriptFeed.value
  if (!element) return
  pinnedToBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight <= 80
}

async function scrollToLatest(force = false) {
  await nextTick()
  const element = transcriptFeed.value
  if (!element || (!force && !pinnedToBottom.value)) return
  element.scrollTop = element.scrollHeight
  pinnedToBottom.value = true
}

watch(
  () => [visibleDialogue.value.map((turn) => turn.text).join(''), props.partialText],
  () => { void scrollToLatest() },
)

watch(() => props.caseId, () => {
  stopBot()
  restoreBotTurns()
  loadBotAnswered()
  void scrollToLatest(true)
})

onMounted(() => {
  restoreBotTurns()
  loadBotAnswered()
  void scrollToLatest(true)
})
</script>

<template>
  <aside class="live-dialogue-panel">
    <header class="live-dialogue-header">
      <div>
        <span class="panel-kicker">原文 / 实时转写</span>
        <h2>实时语音对话</h2>
      </div>
      <div class="live-dialogue-actions">
        <button
          class="bot-toggle"
          :class="{ active: botActive, judging: botJudging || botGenerating }"
          :title="botActive ? '停止 BOT 民警' : 'BOT 扮演民警自动提问（测试用）'"
          @click="toggleBot"
        >{{ botActive ? (botGenerating ? 'BOT 生成中…' : botJudging ? 'BOT 判定中…' : 'BOT 提问中') : 'BOT' }}</button>
        <div class="capture-control">
          <button
            class="capture-toggle"
            :class="{ active: captureRunning }"
            :disabled="captureBusy || !captureAvailable"
            @click="emit('captureToggle')"
        >
          <span class="record-dot"></span>
          {{ captureRunning ? `停止录音 ${elapsed}` : '开始录音' }}
        </button>
        </div>
      </div>
    </header>

    <div class="dialogue-zones">
      <div class="dialogue-upper-zones">
        <section class="dialogue-region waveform-region" aria-label="实时录音波形">
          <div class="region-heading">
            <strong>录音波形</strong>
            <span class="capture-meter-state">
              {{ audioMeterSignal === 'LIVE' ? '实时音频' : audioMeterSignal === 'STALE' ? '暂无新音频信号' : audioMeterSignal === 'WAITING' ? '等待音频输入' : '录音未进行' }}
            </span>
          </div>
          <div class="capture-meter-waveform" role="img" aria-label="实时麦克风输入振幅波形">
            <RecorderWaveformCanvas
              v-if="captureRunning && audioMeterSamples.length"
              :key="captureStatus.captureSessionId ?? 'active-capture'"
              :samples="audioMeterSamples"
            />
            <span v-else class="waveform-placeholder">{{ captureRunning ? '等待音频输入' : '开始录音后显示实时波形' }}</span>
          </div>
        </section>

        <section class="dialogue-region transcript-region" aria-label="实时转写文本">
          <header class="region-heading transcript-heading">
            <div>
              <strong>转写文本 · 第 1 步</strong>
              <AsrWorkflowStatus :capture="captureStatus" stage="transcription" />
            </div>
            <button v-if="!pinnedToBottom" class="latest-inline-button" @click="scrollToLatest(true)">↓ 最新消息</button>
          </header>
          <div ref="transcriptFeed" class="transcript-content" @scroll="onFeedScroll">
            <div v-if="!visibleDialogue.length && !partialText && !captureRunning" class="dialogue-empty">
              <strong>等待现场对话</strong>
              <p>原始转写会在这里连续显示。</p>
            </div>

            <p v-if="visibleDialogue.length || partialText || captureRunning" class="transcript-paragraph">
              <span
                v-for="turn in visibleDialogue"
                :key="turn.key"
                class="transcript-fragment"
                :class="{ selected: dialogueArmed(turn.fragments) }"
                :role="turn.fragments.some((item) => !isBotFragment(item)) ? 'button' : undefined"
                :tabindex="turn.fragments.some((item) => !isBotFragment(item)) ? 0 : undefined"
                :aria-label="turn.fragments.some((item) => !isBotFragment(item)) ? '选择这段转写并放入笔录' : undefined"
                :aria-pressed="turn.fragments.some((item) => !isBotFragment(item)) ? dialogueArmed(turn.fragments) : undefined"
                :data-fragment-id="turn.primary.id"
                :draggable="turn.fragments.some((item) => !isBotFragment(item))"
                @dragstart="startDialogueDrag($event, turn.fragments)"
                @click.stop="armDialogue(turn.fragments)"
                @keydown.enter.prevent="armDialogue(turn.fragments)"
                @keydown.space.prevent="armDialogue(turn.fragments)"
              >{{ turn.text }}</span><span v-if="captureRunning" class="transcript-live-partial" :class="{ idle: !partialText }" aria-live="polite">{{ partialText || (livePreviewUnavailable ? livePreviewUnavailableMessage : '等待识别文字…请说话') }}</span>
            </p>

          </div>
        </section>
      </div>

      <section class="dialogue-region recognition-region" aria-label="说话人识别结果">
        <header class="region-heading recognition-heading">
          <div>
            <strong>说话人识别 · 第 2 步</strong>
            <AsrWorkflowStatus :capture="captureStatus" stage="speaker" />
          </div>
          <span class="recognition-count">{{ recognitionFragments.length }} 段</span>
        </header>
        <div class="recognition-list">
          <details v-if="qaReviewUnits.length || qaResolvedUnits.length" class="qa-review-rail" aria-label="正式笔录归档处理">
            <summary>正式笔录归档处理（{{ qaReviewUnits.length }} 项待处理）</summary>
            <article v-for="unit in qaReviewUnits" :key="unit.id" class="qa-review-card">
              <header><span class="qa-status-chip">待处理</span><small>{{ unit.reasonCode || 'NEEDS_REVIEW' }}</small></header>
              <p v-if="unit.rawQuestionText"><b>原始问：</b>{{ unit.rawQuestionText }}</p>
              <p v-if="unit.rawAnswerText"><b>原始答：</b>{{ unit.rawAnswerText }}</p>
              <p v-if="unit.aiSuggestedQuestionText" class="qa-suggestion"><b>AI 建议问：</b>{{ unit.aiSuggestedQuestionText }}</p>
              <p v-if="unit.aiSuggestedAnswerText" class="qa-suggestion"><b>AI 建议答：</b>{{ unit.aiSuggestedAnswerText }}</p>
              <div class="qa-review-actions">
                <button draggable="true" @dragstart="startWholeQaDrag($event, unit)" @click="armDrop(wholeQaDropEntries(unit), '整组问答')">拖动整组问答</button>
                <button v-if="unit.answerFragmentIds.length" draggable="true" @dragstart="startAnswerDrag($event, unit)" @click="armDrop(answerQaDropEntries(unit), '仅答案')">仅拖动答案</button>
                <button class="qa-ignore" @click="resolveQa(unit, { action: 'IGNORE' })">忽略</button>
              </div>
            </article>
            <div v-for="unit in qaResolvedUnits" :key="`status-${unit.id}`" class="qa-routing-status" :class="{ 'qa-status-muted': unit.status === 'IGNORED' || unit.status === 'ROLLED_BACK' || unit.classification === 'IGNORE' }">
              <span>{{ qaStatusLabel(unit) }}</span>
              <small v-if="unit.rawQuestionText">{{ unit.rawQuestionText }}</small>
              <button v-if="unit.status === 'APPLIED'" class="qa-rollback" @click="rollbackQa(unit)">回退本次匹配</button>
            </div>
          </details>
          <p v-if="!recognitionFragments.length" class="recognition-empty">
            {{ captureRunning ? '等待第 1 步产生文字片段' : '识别结果会显示在这里' }}
          </p>
          <article v-for="item in recognitionFragments" :key="item.id" class="recognition-entry">
            <div class="recognition-row">
              <time class="recognition-time">{{ formatTime(item) }}</time>
              <p class="recognition-excerpt">{{ (item.editedText || item.rawText).trim() }}</p>
              <span class="speaker-result-chip" :class="{ review: recognitionNeedsReview(item) }">{{ speakerName(item) }}</span>
              <span class="recognition-result-state" :class="{ review: recognitionNeedsReview(item) }">{{ recognitionStatusLabel(item) }}</span>
            </div>
            <div class="recognition-entry-actions">
              <button
                type="button"
                class="recognition-transfer-button"
                :class="{ selected: dialogueArmed([item]) }"
                :aria-pressed="dialogueArmed([item])"
                @click.stop="toggleDialogueSelection([item])"
              >{{ dialogueArmed([item]) ? '已选中' : '选择此段' }}</button>
            </div>

            <details v-if="fragmentHistory(item.id).some((history) => history.id !== item.id)" class="fragment-lineage">
              <summary>查看原始转写与说话人分析沿革</summary>
              <div v-for="history in fragmentHistory(item.id)" :key="history.id" class="fragment-lineage-row">
                <strong>{{ history.state === 'SUPERSEDED' ? '原始转写' : '分析后片段' }}</strong>
                <span>{{ history.rawText }}</span>
              </div>
            </details>

            <section v-if="pendingFor(item.id)" class="pending-resolution-card">
              <template v-if="pendingFor(item.id)?.matchStatus === 'UNMATCHED'">
                <p>未匹配正式笔录问题 · 可直接拖到左侧正式笔录指定位置</p>
                <div class="pending-actions">
                  <button class="primary" @click="resolve(pendingFor(item.id)!, { action: 'ADD' })">加入本案笔录</button>
                  <button @click="resolve(pendingFor(item.id)!, { action: 'IGNORE' })">忽略</button>
                </div>
              </template>
              <template v-else-if="pendingFor(item.id)?.matchStatus === 'AMBIGUOUS'">
                <p>可能对应多个正式问题，请人工确认</p>
                <div class="candidate-list">
                  <button
                    v-for="candidate in candidateQuestions(pendingFor(item.id)!)"
                    :key="candidate.id"
                    @click="resolve(pendingFor(item.id)!, { action: 'LINK', caseQuestionId: candidate.id, roundMode: 'NEW_ROUND' })"
                  >对应：{{ candidate.text }}</button>
                </div>
                <div class="pending-actions">
                  <button class="primary" @click="resolve(pendingFor(item.id)!, { action: 'ADD' })">新建本案问题</button>
                  <button @click="resolve(pendingFor(item.id)!, { action: 'IGNORE' })">忽略</button>
                </div>
              </template>
              <template v-else-if="pendingFor(item.id)?.matchStatus === 'MATCHED_EXISTING'">
                <p>该问题已在本案笔录中出现，请选择本次问答如何记录</p>
                <div class="pending-actions">
                  <button
                    v-if="pendingFor(item.id)!.candidateQuestionIds[0]"
                    class="primary"
                    @click="resolve(pendingFor(item.id)!, { action: 'LINK', caseQuestionId: pendingFor(item.id)!.candidateQuestionIds[0], roundMode: 'APPEND_EXISTING' })"
                  >追加到原回答</button>
                  <button
                    v-if="pendingFor(item.id)!.candidateQuestionIds[0]"
                    @click="resolve(pendingFor(item.id)!, { action: 'LINK', caseQuestionId: pendingFor(item.id)!.candidateQuestionIds[0], roundMode: 'NEW_ROUND' })"
                  >新增一轮问答</button>
                </div>
              </template>
            </section>

            <details v-if="item.recognitionRevisions.length || item.state !== 'CONFIRMED'" class="recognition-tools">
              <summary>人工修正{{ item.recognitionRevisions.length ? `（${item.recognitionRevisions.length} 条）` : '' }}</summary>
              <div v-if="item.recognitionRevisions.length" class="revision-history">
                <h4>人工修正历史</h4>
                <div v-for="revision in item.recognitionRevisions" :key="revision.revisionId" class="revision-row">
                  <strong>#{{ revision.revisionNo }}</strong>
                  <span>{{ speakerLabel(revision.beforeSpeaker) }} → {{ speakerLabel(revision.afterSpeaker) }}</span>
                  <span>{{ revision.reason || '未填写原因' }}</span>
                  <span>{{ revision.actorId || '未记录人员' }}</span>
                  <time>{{ formatDate(revision.createdAt) }}</time>
                </div>
              </div>

              <div v-if="item.state !== 'CONFIRMED'" class="recognition-correction">
                <h4>人工修正</h4>
                <p>请确认说话人并填写修正原因。</p>
                <div class="correction-controls">
                  <select
                    :value="correctionRole(item)"
                    @change="correctionSpeaker[item.id] = ($event.target as HTMLSelectElement).value as TemporaryAsrSpeaker"
                  >
                    <option value="SUSPECT">嫌疑人</option>
                    <option value="INTERROGATOR">主审民警</option>
                    <option value="RECORDER">记录民警</option>
                    <option value="UNKNOWN">未知人员</option>
                  </select>
                  <input v-model="correctionReason[item.id]" placeholder="填写人工修正原因（必填）" maxlength="512" />
                  <button class="correction-submit" :disabled="!(correctionReason[item.id] || '').trim()" @click="submitCorrection(item)">保存修正</button>
                </div>
              </div>
            </details>
          </article>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.capture-control .capture-toggle {
  width: 142px;
  min-width: 142px;
}

.dialogue-zones {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px 14px;
  overflow: hidden;
}

.dialogue-upper-zones {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, .7fr) minmax(0, 1.3fr);
  gap: 10px;
}

.dialogue-region {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #d8e3eb;
  border-radius: 10px;
  background: #fff;
}

.region-heading {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px 7px;
  color: #253f58;
  font: 12px/1.45 system-ui, sans-serif;
}

.region-heading strong {
  color: #1f3d5c;
  font-size: 13px;
}

.capture-meter-state {
  color: #72808a;
  font-size: 10px;
  line-height: 1.4;
  white-space: nowrap;
}

.capture-meter-waveform {
  flex: 1 1 auto;
  min-height: 0;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: stretch;
  margin: 0 12px 10px;
}

.waveform-placeholder {
  display: grid;
  place-items: center;
  width: 100%;
  color: #8291a0;
  font-size: 11px;
}

.transcript-heading > div,
.recognition-heading > div {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.transcript-content,
.recognition-list {
  min-height: 0;
  flex: 1 1 auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.transcript-content {
  padding: 0 14px 12px;
  scroll-behavior: smooth;
}

.transcript-paragraph {
  margin: 0;
  color: #1f2731;
  font-size: 13px;
  line-height: 1.75;
  white-space: normal;
  overflow-wrap: anywhere;
}

.transcript-fragment {
  cursor: text;
}

.transcript-fragment.selected {
  background: #e7f0ff;
}

.transcript-live-partial {
  color: #2874e5;
}

.transcript-live-partial.idle {
  color: #8291a0;
}

.latest-inline-button {
  flex: 0 0 auto;
  border: 1px solid #91a9ba;
  border-radius: 999px;
  padding: 3px 8px;
  color: #355776;
  background: #fff;
  font-size: 10px;
  cursor: pointer;
}

.recognition-count {
  flex: 0 0 auto;
  color: #73869a;
  font-size: 10px;
}

.recognition-list {
  padding: 0 12px 10px;
}

.recognition-entry {
  padding: 5px 0;
  border-top: 1px solid #edf1f5;
}

.recognition-row {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 7px;
  min-height: 30px;
}

.recognition-entry-actions {
  display: flex;
  justify-content: flex-end;
  padding: 0 2px 3px;
}

.recognition-transfer-button {
  border: 1px solid #9bb4cc;
  border-radius: 999px;
  padding: 3px 9px;
  color: #285dba;
  background: #fff;
  font-size: 10px;
  cursor: pointer;
}

.recognition-transfer-button.selected {
  border-color: #2874e5;
  color: #fff;
  background: #2874e5;
}

.recognition-time {
  color: #728194;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.recognition-excerpt {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #34465a;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.speaker-result-chip {
  max-width: 130px;
  overflow: hidden;
  border-radius: 999px;
  padding: 3px 8px;
  color: #285dba;
  background: #e8f1ff;
  font-size: 10px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.speaker-result-chip.review {
  color: #a36611;
  background: #fff3dd;
}

.recognition-result-state {
  color: #278154;
  font-size: 10px;
  white-space: nowrap;
}

.recognition-result-state.review {
  color: #a36611;
}

.recognition-empty {
  margin: 12px 2px;
  color: #8291a0;
  font-size: 11px;
}

@media (max-width: 1100px) {
  .recognition-row {
    grid-template-columns: 54px minmax(0, 1fr) auto;
  }
  .recognition-result-state {
    grid-column: 2 / -1;
    margin-top: -4px;
  }
}

.fragment-lineage {
  margin: 8px 0 0;
  padding: 7px 9px;
  border: 1px solid #d7e2ec;
  border-radius: 8px;
  color: #52677b;
  background: #f8fbfd;
  font-size: 12px;
}

.fragment-lineage summary {
  cursor: pointer;
}

.fragment-lineage-row {
  display: flex;
  gap: 8px;
  padding-top: 6px;
}

.speaker-prefix { color: #173f69; }
.evidence-title { font-weight: 700; color: #23384d; }
.evidence-store-badge {
  padding: 2px 6px;
  border-radius: 999px;
  background: #e6f6ed;
  color: #246a45;
  font-weight: 700;
}
.partial-turn .dialogue-bubble { border-style: solid; }
.partial-turn.idle .dialogue-bubble { opacity: .4; }
.revision-history,
.recognition-correction {
  margin: 0 10px 10px;
  padding-top: 9px;
  border-top: 1px solid rgba(76, 112, 156, .16);
}
.revision-history h4,
.recognition-correction h4 { margin: 0 0 6px; font-size: 12px; color: #27394b; }
.revision-row {
  display: grid;
  grid-template-columns: auto 1fr 1.4fr 1fr auto;
  gap: 6px;
  padding: 5px 0;
  color: #586879;
}
.recognition-correction p { margin: 0 0 7px; color: #6a7785; }
.correction-controls { display: grid; grid-template-columns: 120px 1fr auto; gap: 6px; }
.correction-controls select,
.correction-controls input {
  min-width: 0;
  border: 1px solid #cbd5df;
  border-radius: 7px;
  padding: 6px 8px;
  background: #fff;
}
.correction-submit {
  border: 0;
  border-radius: 7px;
  padding: 6px 10px;
  background: #315f8d;
  color: white;
  cursor: pointer;
}
.correction-submit:disabled { opacity: .45; cursor: not-allowed; }
@media (max-width: 900px) {
  .revision-row { grid-template-columns: auto 1fr; }
  .correction-controls { grid-template-columns: 1fr; }
}
.recognition-tools { margin-top: 6px; color: #52677b; font-size: 11px; }
.recognition-tools summary { cursor: pointer; padding: 4px; }
.qa-review-rail { margin-bottom: 10px; color: #647587; font-size: 12px; }
.qa-review-rail summary { cursor: pointer; padding: 4px 2px; }
.qa-review-rail[open] { display: grid; gap: 8px; }
.qa-review-card { border: 1px solid #d5a73f; background: #fff9e8; border-radius: 10px; padding: 10px; }
.qa-review-card header { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.qa-review-card p { margin: 6px 0; line-height: 1.45; }
.qa-status-chip { display: inline-flex; padding: 2px 8px; border-radius: 999px; background: #f3c760; color: #5b4308; font-weight: 800; }
.qa-suggestion { color: #536274; }
.qa-review-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.qa-review-actions button { cursor: grab; }
.qa-review-actions .qa-ignore { cursor: pointer; }
.qa-routing-status { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border-radius: 8px; background: #edf6ef; color: #2d6040; font-size: 12px; }
.qa-routing-status small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qa-rollback { margin-left: auto; border: 1px solid #d6a33a; border-radius: 6px; padding: 3px 7px; background: #fff; color: #815d13; cursor: pointer; }
.qa-status-muted { background: #f2f3f5; color: #7a8088; opacity: .78; }
.raw-fragment-list { display: grid; gap: 6px; padding: 9px 10px; border-top: 1px solid rgba(76, 112, 156, .16); }
.raw-fragment-list div { display: grid; gap: 2px; }
.raw-fragment-list strong { color: #334b62; }
.raw-fragment-list small { color: #728194; }
</style>
