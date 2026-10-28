<script setup lang="ts">
import { computed } from 'vue'
import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * ④ 定稿校验 · 右栏「询问笔录预览」（样板 P13）
 *
 * 只读：按顺序列出全部问答，未作答的题如实标「（未获取）」，已录未摘入的标出来提醒回到③处理。
 */
const props = defineProps<{ questions: FormalQuestion[] }>()

const entries = computed(() => [...props.questions]
  .filter((question) => question.active !== false)
  .sort((a, b) => a.sortOrder - b.sortOrder)
  .map((question) => {
    const answer = question.formalAnswerText?.trim() || ''
    const drafted = !answer && Boolean(question.rounds?.some((round) => round.status !== 'DETACHED' && round.answerText?.trim()))
    return { id: question.id, text: question.text, answer, drafted }
  }))
const answered = computed(() => entries.value.filter((entry) => entry.answer).length)
const chars = computed(() => entries.value.reduce((total, entry) => total + entry.text.length + entry.answer.length, 0))
</script>

<template>
  <section class="review-preview" aria-label="询问笔录预览">
    <header class="review-preview-head">
      <strong>询问笔录预览</strong>
      <span>{{ answered }} 问已答 · {{ entries.length - answered }} 题未获取 · {{ chars }} 字</span>
    </header>
    <ol class="review-preview-body">
      <li v-for="entry in entries" :key="entry.id" :data-question-id="entry.id">
        <p>问：{{ entry.text }}</p>
        <p v-if="entry.answer">答：{{ entry.answer }}</p>
        <p v-else class="is-missing">答：（未获取）<small v-if="entry.drafted">已录音但未摘入正本，可「返回修改」到③摘入</small></p>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.review-preview { display: flex; flex-direction: column; gap: var(--space-4); min-height: 0; padding: var(--space-6) var(--space-8); overflow: auto; border-radius: var(--radius-lg); background: var(--surface); }
.review-preview-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-4); }
.review-preview-head strong, .review-preview-head span { color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.review-preview-body { display: flex; flex-direction: column; gap: var(--space-5); margin: 0; padding: 0; list-style: none; }
.review-preview-body p { margin: 0; color: var(--ink-700); font-size: var(--text-md); line-height: 1.7; }
.review-preview-body .is-missing { color: var(--ink-400); }
.review-preview-body small { margin-left: var(--space-3); color: var(--warning-700); font-size: var(--text-xs); }
</style>
