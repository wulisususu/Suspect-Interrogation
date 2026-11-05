<script setup lang="ts">
import { computed } from 'vue'
import type { CaseSummary, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import RecordPaper from './RecordPaper.vue'

/**
 * ④ 定稿校验 · 右栏「询问笔录预览」
 *
 * 与签署页、打印件同一份纸面（A4 逐页、宋体、横线、页码），定稿前看到的就是将要打印的样子。
 * 未作答的题如实印「（未获取）」；已录音但未摘入正本的题在纸面上方单独提醒，回到③处理。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
}>()

const entries = computed(() => [...props.questions]
  .filter((question) => question.active !== false)
  .sort((a, b) => a.sortOrder - b.sortOrder)
  .map((question, index) => {
    const answer = question.formalAnswerText?.trim() || ''
    const drafted = !answer && Boolean(question.rounds?.some((round) => round.status !== 'DETACHED' && round.answerText?.trim()))
    return { id: question.id, ordinal: index + 1, text: question.text, answer, drafted }
  }))
const answered = computed(() => entries.value.filter((entry) => entry.answer).length)
const chars = computed(() => entries.value.reduce((total, entry) => total + entry.text.length + entry.answer.length, 0))
const drafted = computed(() => entries.value.filter((entry) => entry.drafted))
</script>

<template>
  <section class="review-preview" aria-label="询问笔录预览">
    <header class="review-preview-head">
      <strong>询问笔录预览</strong>
      <span>{{ answered }} 问已答 · {{ entries.length - answered }} 题未获取 · {{ chars }} 字</span>
      <small>与打印件一致</small>
    </header>
    <p v-if="drafted.length" class="review-preview-drafted">
      第 {{ drafted.map((entry) => entry.ordinal).join('、') }} 题已录音但未摘入正本，纸面上印为「（未获取）」，可「返回修改」到③摘入
    </p>
    <div class="review-preview-paper">
      <RecordPaper :summary="summary" :facts="facts" :session="session" :questions="questions" />
    </div>
  </section>
</template>

<style scoped>
.review-preview { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; padding: var(--space-5) var(--space-6); overflow: hidden; border-radius: var(--radius-lg); background: var(--surface-muted); }
.review-preview-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-4); }
.review-preview-head strong, .review-preview-head span { color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.review-preview-head small { margin-left: auto; color: var(--ink-400); font-size: var(--text-xs); }
.review-preview-drafted { margin: 0; padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-sm); }
.review-preview-paper { flex: 1; min-height: 0; overflow: auto; padding: var(--space-2); }
</style>
