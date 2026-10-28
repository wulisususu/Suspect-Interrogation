<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowRight, ChevronRight, FileText, Mic, Pause, Play, Plus, RotateCcw, Square } from '@lucide/vue'
import type { AudioLevelSample } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import RecorderWaveformCanvas from './RecorderWaveformCanvas.vue'

/**
 * 草稿 · 一问一答（样板 P07 左栏，交互状态 A / B）
 *
 * 一道题一张卡，点卡即录、录完即转：
 * 未开始 →（点击此处回答）→ 录音中 →（结束并转写）→ 待摘入 →（摘入正本）→ 已入正本。
 * 录音按题归属，不依赖说话人识别；答区可直接改，待摘入改的是草稿，已入正本改的是正本。
 */
const props = defineProps<{
  questions: FormalQuestion[]
  sessionStatus: string
  /** 正在为哪道题录音；null 表示没有逐题录音 */
  recordingQuestionId: string | null
  /** 正在按住说话追加一问 */
  questionRecording?: boolean
  captureBusy?: boolean
  captureAvailable?: boolean
  captureElapsedMs?: number
  audioLevels?: AudioLevelSample[]
  liveText?: string
  locked?: boolean
}>()

const emit = defineEmits<{
  locate: [questionId: string]
  record: [questionId: string, replace: boolean]
  stop: []
  commit: [questionId: string, answerText: string]
  updateDraft: [roundId: string, answerText: string]
  updateAnswer: [questionId: string, answerText: string]
  addQuestion: [text: string, afterQuestionId: string | null]
  questionHoldStart: [afterQuestionId: string | null]
  questionHoldEnd: []
  togglePause: []
}>()

type CardState = 'recorded' | 'draft' | 'recording' | 'empty'

const STATE_LABEL: Record<CardState, string> = {
  recorded: '已入正本',
  draft: '待摘入',
  recording: '● 录音中',
  empty: '未开始',
}

const selectedId = ref<string | null>(null)

const cards = computed(() => [...props.questions]
  .filter((question) => question.active !== false)
  .sort((a, b) => a.sortOrder - b.sortOrder)
  .map((question, index) => {
    const answer = question.formalAnswerText?.trim() || ''
    const round = [...(question.rounds ?? [])].reverse().find((item) => item.status !== 'DETACHED') ?? null
    const draft = round?.answerText?.trim() || ''
    let state: CardState = 'empty'
    if (props.recordingQuestionId === question.id) state = 'recording'
    else if (answer) state = 'recorded'
    else if (draft) state = 'draft'
    return { id: question.id, ordinal: index + 1, text: question.text, answer, draft, roundId: round?.id ?? null, state }
  }))

/** 本地编辑：只保存真正改过的内容，避免服务端刷新冲掉正在输入的文字。 */
const edits = reactive<Record<string, string>>({})
watch(
  () => cards.value.map((card) => `${card.id}\u0000${card.state}\u0000${card.answer}\u0000${card.draft}`).join('\u0001'),
  () => {
    for (const card of cards.value) edits[card.id] = card.state === 'recorded' ? card.answer : card.draft
  },
  { immediate: true },
)

const recording = computed(() => Boolean(props.recordingQuestionId) || Boolean(props.questionRecording))
const sessionClosed = computed(() => ['COMPLETED', 'CANCELLED'].includes(props.sessionStatus))
const answerBlockedReason = computed(() => {
  if (props.locked) return '笔录已冻结'
  if (sessionClosed.value) return '本次询问已结束'
  if (props.sessionStatus === 'PAUSED') return '询问已暂停，继续询问后可录音'
  if (!props.captureAvailable) return '录音设备未就绪'
  return ''
})
const canStartAnswer = computed(() => !answerBlockedReason.value && !recording.value && !props.captureBusy)

const elapsedText = computed(() => {
  const total = Math.floor((props.captureElapsedMs ?? 0) / 1000)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
})

const counts = computed(() => ({
  total: cards.value.length,
  recorded: cards.value.filter((card) => card.state === 'recorded').length,
}))

function select(cardId: string) {
  selectedId.value = cardId
}

function record(cardId: string, replace = false) {
  if (!canStartAnswer.value) return
  selectedId.value = cardId
  emit('record', cardId, replace)
}

function saveEdit(cardId: string) {
  if (props.locked) return
  const card = cards.value.find((item) => item.id === cardId)
  if (!card) return
  const next = (edits[cardId] ?? '').trim()
  if (card.state === 'recorded' && next !== card.answer) emit('updateAnswer', cardId, next)
  else if (card.state === 'draft' && card.roundId && next && next !== card.draft) emit('updateDraft', card.roundId, next)
}

function commit(cardId: string) {
  const text = (edits[cardId] ?? '').trim()
  if (props.locked || !text) return
  emit('commit', cardId, text)
}

/** 追加一问：按住说话、松开成卡；录音不可用或想打字时改为手动输入。 */
const typing = ref(false)
const newQuestion = ref('')
const lastCardId = computed(() => cards.value.at(-1)?.id ?? null)
let holding = false

function holdStart(event: PointerEvent) {
  if (!canStartAnswer.value) { typing.value = true; return }
  holding = true
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  emit('questionHoldStart', lastCardId.value)
}
function holdEnd() {
  if (!holding) return
  holding = false
  emit('questionHoldEnd')
}
function submitQuestion() {
  const text = newQuestion.value.trim()
  if (!text || props.locked) return
  emit('addQuestion', text, lastCardId.value)
  newQuestion.value = ''
  typing.value = false
}
</script>

<template>
  <section class="draft-rail" aria-label="逐题草稿">
    <header class="draft-rail-head">
      <strong>草稿 · 一问一答</strong>
      <span class="draft-count">{{ counts.total }} 卡 · {{ counts.recorded }} 已入正本<template v-if="recordingQuestionId"> · 1 卡录制中</template></span>
      <span v-if="recording" class="draft-live"><i aria-hidden="true"></i>录音中 {{ elapsedText }} · 边录边转</span>
      <span v-else-if="sessionStatus === 'READY' && !locked" class="draft-hint">点任一题卡的「点击此处回答」即开始询问</span>
      <button
        v-if="sessionStatus === 'RUNNING' || sessionStatus === 'PAUSED'"
        type="button"
        class="draft-pause"
        :disabled="locked || recording || captureBusy"
        @click="emit('togglePause')"
      >
        <Play v-if="sessionStatus === 'PAUSED'" :size="15" aria-hidden="true" /><Pause v-else :size="15" aria-hidden="true" />
        {{ sessionStatus === 'PAUSED' ? '继续询问' : '暂停询问' }}
      </button>
    </header>

    <ol v-if="cards.length" class="draft-list">
      <li v-for="card in cards" :key="card.id">
        <article
          class="draft-card"
          :class="[`is-${card.state}`, { 'is-selected': selectedId === card.id && card.state !== 'recording' }]"
          :data-question-id="card.id"
          @click="select(card.id)"
        >
          <header class="draft-card-head">
            <span class="draft-ordinal">Q{{ card.ordinal }}</span>
            <p class="draft-question">{{ card.text }}</p>
            <span class="draft-state">{{ STATE_LABEL[card.state] }}<template v-if="card.state === 'draft' && selectedId === card.id"> · 已选中</template></span>
          </header>

          <div v-if="card.state === 'recording'" class="draft-recording">
            <div class="draft-recording-meter">
              <span class="draft-timer">录音中 {{ elapsedText }}</span>
              <RecorderWaveformCanvas v-if="audioLevels?.length" class="draft-wave" :samples="audioLevels" :max-height="22" :bar-width="3" :bar-gap="3" :sample-limit="24" />
              <button type="button" class="draft-stop" :disabled="captureBusy" @click.stop="emit('stop')"><Square :size="14" aria-hidden="true" />结束并转写</button>
            </div>
            <p class="draft-live-text">{{ liveText || '请对着话筒回答，转写文字会实时出现在这里……' }}</p>
          </div>

          <template v-else-if="card.state === 'recorded' || card.state === 'draft'">
            <textarea
              v-model="edits[card.id]"
              class="draft-answer"
              rows="2"
              :aria-label="`第 ${card.ordinal} 题回答`"
              :disabled="locked"
              @blur="saveEdit(card.id)"
            ></textarea>
            <footer class="draft-actions">
              <button type="button" class="draft-action is-secondary" :disabled="!canStartAnswer" @click.stop="record(card.id, true)"><RotateCcw :size="15" aria-hidden="true" />重录这题</button>
              <button v-if="card.state === 'recorded'" type="button" class="draft-action is-link" @click.stop="emit('locate', card.id)"><FileText :size="15" aria-hidden="true" />在正本中查看<ChevronRight :size="15" aria-hidden="true" /></button>
              <button v-else type="button" class="draft-action is-commit" :disabled="locked" @click.stop="commit(card.id)">摘入正本<ArrowRight :size="16" aria-hidden="true" /></button>
            </footer>
          </template>

          <div v-else class="draft-empty">
            <button type="button" class="draft-action is-answer" :disabled="!canStartAnswer" @click.stop="record(card.id)"><Mic :size="16" aria-hidden="true" />点击此处回答</button>
            <small>{{ answerBlockedReason || '对着话筒说话 · 说完再点一下结束 · 自动转成文字，可再修改' }}</small>
          </div>
        </article>
      </li>
    </ol>
    <p v-else class="draft-none">本案暂无问题，可在下方追加一问。</p>

    <form v-if="typing" class="draft-add-form" @submit.prevent="submitQuestion">
      <input v-model="newQuestion" type="text" placeholder="输入要追加的问题" aria-label="追加问题" :disabled="locked" />
      <button type="submit" class="draft-action is-commit" :disabled="locked || !newQuestion.trim()">成卡</button>
      <button type="button" class="draft-action is-secondary" @click="typing = false">取消</button>
    </form>
    <div v-else class="draft-add">
      <button
        type="button"
        class="draft-add-hold"
        :class="{ 'is-holding': questionRecording }"
        :disabled="locked"
        @pointerdown="holdStart"
        @pointerup="holdEnd"
        @pointercancel="holdEnd"
      ><Plus :size="15" aria-hidden="true" />{{ questionRecording ? `正在听问题 ${elapsedText} · 松开即成卡` : '追加一问 · 按住说话，说完自动成卡' }}</button>
      <button type="button" class="draft-add-type" :disabled="locked" @click="typing = true">手动输入</button>
    </div>
  </section>
</template>

<style scoped>
.draft-rail { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; padding: var(--space-4) var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.draft-rail-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.draft-rail-head strong { color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.draft-count { padding: 2px var(--space-3); border-radius: var(--radius-pill); background: var(--primary-100); color: var(--primary-600); font-size: var(--text-xs); }
.draft-live { display: inline-flex; align-items: center; gap: var(--space-2); margin-left: auto; color: var(--danger-600); font-size: var(--text-sm); }
.draft-live i { width: 10px; height: 10px; border-radius: 50%; background: var(--danger-600); }
.draft-hint { margin-left: auto; color: var(--ink-400); font-size: var(--text-xs); }
.draft-pause { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 40px; padding: 0 var(--space-4); border: 1px solid var(--danger-600); border-radius: var(--radius-sm); background: var(--danger-100); color: var(--danger-600); font-size: var(--text-sm); font-weight: 600; }
.draft-live + .draft-pause, .draft-hint + .draft-pause { margin-left: 0; }
.draft-count + .draft-pause { margin-left: auto; }

.draft-list { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; margin: 0; padding: 0; overflow: auto; list-style: none; }
.draft-card { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-3) var(--space-4); border: 1px solid var(--line-200); border-radius: var(--radius-md); background: var(--surface); }
.draft-card.is-selected { border: 2px solid var(--primary-600); }
.draft-card.is-recording { border: 2px solid var(--danger-600); background: var(--danger-100); }
.draft-card.is-empty { background: var(--surface-sunken); }
.draft-card-head { display: flex; align-items: flex-start; gap: var(--space-3); }
.draft-ordinal { flex: none; padding: 1px var(--space-2); border-radius: var(--radius-sm); background: var(--primary-100); color: var(--primary-600); font-size: var(--text-xs); font-weight: 650; }
.draft-card.is-selected .draft-ordinal { background: var(--primary-600); color: var(--surface); }
.draft-card.is-recording .draft-ordinal { background: var(--danger-600); color: var(--surface); }
.draft-card.is-empty .draft-ordinal { background: var(--surface-muted); color: var(--ink-400); }
.draft-question { flex: 1; margin: 0; color: var(--ink-900); font-size: var(--text-md); line-height: 1.5; }
.draft-card.is-empty .draft-question { color: var(--ink-500); }
.draft-state { flex: none; color: var(--ink-400); font-size: var(--text-xs); }
.draft-card.is-recorded .draft-state { color: var(--success-700); }
.draft-card.is-draft .draft-state { color: var(--warning-700); }
.draft-card.is-recording .draft-state { color: var(--danger-600); }

.draft-answer { width: 100%; min-height: 64px; padding: var(--space-3) var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--ink-900); font: inherit; font-size: var(--text-md); line-height: 1.7; resize: vertical; }
.draft-card.is-selected .draft-answer { border-color: var(--primary-500); }
.draft-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
.draft-action { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 44px; padding: 0 var(--space-4); border: 0; border-radius: var(--radius-sm); font-size: var(--text-sm); font-weight: 600; }
.draft-action.is-secondary { background: var(--primary-50); color: var(--primary-600); }
.draft-action.is-link { background: transparent; color: var(--primary-600); }
.draft-action.is-commit { border: 1px solid var(--primary-600); background: var(--surface); color: var(--primary-600); }
.draft-action.is-answer { padding: 0 var(--space-6); border-radius: var(--radius-pill); background: var(--primary-600); color: var(--surface); }

.draft-recording { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3) var(--space-4); border: 1px solid var(--danger-600); border-radius: var(--radius-sm); background: var(--surface); }
.draft-recording-meter { display: flex; align-items: center; gap: var(--space-3); }
.draft-timer { color: var(--danger-600); font-size: var(--text-sm); font-variant-numeric: tabular-nums; }
.draft-wave { width: 72px; height: 24px; color: var(--danger-600); }
.draft-stop { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 44px; margin-left: auto; padding: 0 var(--space-5); border: 0; border-radius: var(--radius-sm); background: var(--danger-600); color: var(--surface); font-size: var(--text-md); font-weight: 600; }
.draft-live-text { margin: 0; color: var(--ink-700); font-size: var(--text-md); line-height: 1.7; }

.draft-empty { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-4); border: 1px dashed var(--primary-500); border-radius: var(--radius-sm); }
.draft-empty small { color: var(--ink-400); font-size: var(--text-xs); text-align: center; }
.draft-none { margin: 0; color: var(--ink-400); font-size: var(--text-sm); }

.draft-add { display: flex; gap: var(--space-2); }
.draft-add-hold { display: inline-flex; flex: 1; align-items: center; justify-content: center; gap: var(--space-1); min-height: 44px; border: 1px dashed var(--primary-500); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-sm); font-weight: 600; touch-action: none; user-select: none; }
.draft-add-hold.is-holding { border-style: solid; background: var(--danger-100); color: var(--danger-600); }
.draft-add-type { min-height: 44px; padding: 0 var(--space-3); border: 0; background: transparent; color: var(--ink-500); font-size: var(--text-xs); }
.draft-add-form { display: flex; gap: var(--space-2); }
.draft-add-form input { flex: 1; min-height: 44px; padding: 0 var(--space-3); border: 1px solid var(--primary-500); border-radius: var(--radius-sm); font: inherit; font-size: var(--text-md); }
</style>
