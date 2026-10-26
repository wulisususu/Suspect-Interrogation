<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { Mic, Square } from '@lucide/vue'
import type { FormalQAUnit, FormalQuestion, PendingFormalQuestion } from '../types/templateInterrogation'

/**
 * 草稿 · 逐题卡片流
 *
 * 样板里左栏的主体是「一道题一张卡」：问什么、答了什么、入没入正本一目了然，
 * 答文当场能改，改完即回写正本；录音入口收在卡片栏顶部，不再占一屏。
 */
const props = defineProps<{
  questions: FormalQuestion[]
  qaUnits: FormalQAUnit[]
  pendingQuestions: PendingFormalQuestion[]
  captureRunning: boolean
  captureBusy?: boolean
  captureAvailable?: boolean
  locked?: boolean
}>()

const emit = defineEmits<{
  locate: [questionId: string]
  updateAnswer: [questionId: string, answerText: string]
  captureToggle: []
}>()

type DraftState = 'recorded' | 'buffered' | 'review' | 'empty'

const STATE_LABEL: Record<DraftState, string> = {
  recorded: '已入正本',
  buffered: '待入正本',
  review: '待处理',
  empty: '待补充',
}

const cards = computed(() => {
  const reviewQuestionIds = new Set(
    props.qaUnits
      .filter((unit) => ['OPEN', 'CLOSED', 'ROUTING', 'NEEDS_REVIEW'].includes(unit.status))
      .map((unit) => unit.targetQuestionId)
      .filter((id): id is string => Boolean(id)),
  )
  const pendingQuestionIds = new Set(
    props.pendingQuestions
      .filter((item) => item.status === 'PENDING' || item.status === 'DEFERRED')
      .map((item) => item.id),
  )

  return [...props.questions]
    .filter((question) => question.active !== false)
    .sort((a, b) => a.sortOrder - b.sortOrder)
    .map((question, index) => {
      const canonical = question.formalAnswerText?.trim() || ''
      const bufferedText = question.rounds?.find((round) => round.answerText?.trim())?.answerText?.trim() || ''
      let state: DraftState = 'empty'
      if (canonical) state = 'recorded'
      else if (reviewQuestionIds.has(question.id) || pendingQuestionIds.has(question.id)) state = 'review'
      else if (bufferedText) state = 'buffered'

      return {
        id: question.id,
        ordinal: index + 1,
        text: question.text,
        answer: canonical,
        bufferedText,
        state,
        stateLabel: STATE_LABEL[state],
      }
    })
})

/** 本地编辑草稿：只保存用户真正改过的题，避免服务端刷新把正在输入的内容冲掉 */
const drafts = reactive<Record<string, string>>({})

watch(
  () => cards.value.map((card) => `${card.id}\u0000${card.answer}`).join('\u0001'),
  () => {
    for (const card of cards.value) {
      if (drafts[card.id] === undefined) drafts[card.id] = card.answer
    }
    for (const id of Object.keys(drafts)) {
      if (!cards.value.some((card) => card.id === id)) delete drafts[id]
    }
  },
  { immediate: true },
)

function saveAnswer(cardId: string) {
  if (props.locked) return
  const next = (drafts[cardId] ?? '').trim()
  const current = (cards.value.find((card) => card.id === cardId)?.answer ?? '').trim()
  if (next === current) return
  emit('updateAnswer', cardId, next)
}

const counts = computed(() => {
  const total = cards.value.length
  const recorded = cards.value.filter((card) => card.state === 'recorded').length
  return { total, recorded, remaining: total - recorded }
})
</script>

<template>
  <section class="draft-rail" aria-label="逐题草稿">
    <header class="draft-rail-head">
      <div class="draft-rail-title">
        <strong>草稿 · 一问一答</strong>
        <small>{{ counts.recorded }} / {{ counts.total }} 题已入正本</small>
      </div>
      <button
        type="button"
        class="draft-record"
        :class="{ running: captureRunning }"
        :disabled="captureBusy || captureAvailable === false"
        :title="captureAvailable === false ? '麦克风或识别服务未就绪' : captureRunning ? '结束这一段并转写' : '开始录音，边说边出字'"
        @click="emit('captureToggle')"
      >
        <Square v-if="captureRunning" :size="14" :stroke-width="2.5" />
        <Mic v-else :size="15" />
        {{ captureRunning ? '结束并转写' : '开始录音' }}
      </button>
    </header>

    <ol v-if="cards.length" class="draft-list">
      <li v-for="card in cards" :key="card.id">
        <article class="draft-card" :class="`is-${card.state}`">
          <header class="draft-card-head">
            <span class="draft-ordinal">{{ card.ordinal }}</span>
            <button type="button" class="draft-question" :title="`在正本中定位第 ${card.ordinal} 题`" @click="emit('locate', card.id)">
              {{ card.text }}
            </button>
            <span class="draft-state">{{ card.stateLabel }}</span>
          </header>

          <label class="draft-answer-field">
            <span class="draft-answer-label">答</span>
            <textarea
              v-model="drafts[card.id]"
              rows="2"
              :readonly="locked"
              :placeholder="card.bufferedText ? `已录到：${card.bufferedText}` : '对着话筒说话，或在这里直接录入'"
              @blur="saveAnswer(card.id)"
            ></textarea>
          </label>
        </article>
      </li>
    </ol>

    <p v-else class="draft-empty">选定模板后，题目会逐条出现在这里。</p>
  </section>
</template>

<style scoped>
.draft-rail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  background: var(--surface);
}

.draft-rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--line-100);
}
.draft-rail-title { display: flex; align-items: baseline; gap: var(--space-2); min-width: 0; }
.draft-rail-title strong { font-size: var(--text-base); color: var(--ink-900); }
.draft-rail-title small { color: var(--ink-400); font-size: var(--text-xs); white-space: nowrap; }

.draft-record {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--primary-200);
  border-radius: var(--radius-pill);
  background: var(--primary-50);
  color: var(--primary-700);
  font-size: var(--text-sm);
  white-space: nowrap;
}
.draft-record:hover:not(:disabled) { background: var(--primary-100); }
.draft-record.running {
  border-color: var(--danger-100);
  background: var(--danger-100);
  color: var(--danger-700);
}
.draft-record:disabled { opacity: 0.5; cursor: not-allowed; }

.draft-list {
  margin: 0;
  padding: var(--space-2);
  list-style: none;
  overflow: auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.draft-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--line-200);
  border-radius: var(--radius-md);
  background: var(--surface);
  transition: border-color 0.16s ease;
}
.draft-card:hover { border-color: var(--primary-200); }
.draft-card.is-review { border-color: var(--warning-100); background: var(--warning-100); }
.draft-card.is-buffered { border-color: var(--primary-200); background: var(--primary-50); }

.draft-card-head { display: flex; align-items: flex-start; gap: var(--space-2); }

.draft-ordinal {
  flex: 0 0 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--surface-muted);
  color: var(--ink-500);
  font-size: var(--text-xs);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.draft-card.is-recorded .draft-ordinal { background: var(--success-100); color: var(--success-700); }
.draft-card.is-review .draft-ordinal { background: var(--warning-100); color: var(--warning-700); }

.draft-question {
  flex: 1 1 auto;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink-900);
  font-size: var(--text-base);
  line-height: 1.5;
  text-align: left;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.draft-question:hover { color: var(--primary-600); }

.draft-state {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-muted);
  color: var(--ink-400);
  font-size: var(--text-xs);
  white-space: nowrap;
}
.draft-card.is-recorded .draft-state { background: var(--success-100); color: var(--success-700); }
.draft-card.is-buffered .draft-state { background: var(--primary-100); color: var(--primary-700); }
.draft-card.is-review .draft-state { background: var(--warning-100); color: var(--warning-700); }

.draft-answer-field { display: flex; align-items: flex-start; gap: var(--space-2); }
.draft-answer-label { flex: 0 0 auto; padding-top: 6px; color: var(--ink-400); font-size: var(--text-sm); }
.draft-answer-field textarea {
  flex: 1 1 auto;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--ink-700);
  font-size: var(--text-base);
  line-height: 1.6;
  resize: vertical;
}
.draft-answer-field textarea:hover:not([readonly]) { border-color: var(--line-300); }
.draft-answer-field textarea:focus { border-color: var(--primary-200); background: var(--surface); }
.draft-answer-field textarea[readonly] { color: var(--ink-500); }

.draft-empty {
  margin: 0;
  padding: var(--space-6) var(--space-4);
  color: var(--ink-300);
  font-size: var(--text-sm);
  text-align: center;
}
</style>
