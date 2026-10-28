<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, Check } from '@lucide/vue'
import type { CaseSummary, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * ③ 问答录入 · 正本实时预览（样板 P07 右栏）
 *
 * 只读：抬头机关名与「询问笔录」，紧凑的身份与询问信息行，正文只排已作答与待摘入的问答。
 * 编辑在左栏题卡与②建档完成；④定稿校验仍使用可编辑的纸面。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  busy?: boolean
  locked?: boolean
}>()

const emit = defineEmits<{ commit: [questionId: string, answerText: string] }>()

function fact(key: string) {
  const value = props.facts.find((item) => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : ''
}
const text = (value?: string | null, placeholder = ['待录入', '当前警官']) => (value && !placeholder.includes(value) ? value : '')

function recordTime(value?: number | null) {
  if (!value) return ''
  const d = new Date(value)
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日 ${d.getHours()} 时 ${String(d.getMinutes()).padStart(2, '0')} 分`
}
function birth(value?: string) {
  const match = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(value || '')
  return match ? `${match[1]} 年 ${Number(match[2])} 月 ${Number(match[3])} 日` : value || ''
}
function maskId(value?: string) {
  const id = value || ''
  return id.length > 8 ? `${id.slice(0, 4)}${'*'.repeat(id.length - 8)}${id.slice(-4)}` : id
}

const unit = computed(() => fact('officer_unit'))
const officer = computed(() => text(props.summary.officerName))
const recorder = computed(() => fact('recorder_name'))
const meta = computed(() => {
  const start = recordTime(props.session.startedAt || props.summary.createdAt)
  const end = props.session.endedAt ? recordTime(props.session.endedAt) : ''
  const withUnit = (name: string, unitName: string) => (name ? `${name}${unitName ? `（工作单位：${unitName}）` : ''}` : '')
  return [
    [['时间', start ? `${start} 至 ${end || '　　'}` : '']],
    [['地点', fact('interrogation_place')]],
    [['询问人', withUnit(officer.value, unit.value)]],
    [['记录人', withUnit(recorder.value, fact('recorder_unit') || unit.value)]],
    [['被询问人', text(props.summary.suspectName)], ['性别', props.summary.gender || ''], ['出生日期', birth(props.summary.birthDate)]],
    [['身份证件种类及号码', props.summary.idNumber ? `${fact('id_document_type') || '居民身份证'} ${maskId(props.summary.idNumber)}` : '']],
    [['联系方式', fact('contact')], ['现住址', fact('current_address')]],
    [['户籍所在地', fact('household_registration')]],
  ]
})

const entries = computed(() => [...props.questions]
  .filter((question) => question.active !== false)
  .sort((a, b) => a.sortOrder - b.sortOrder)
  .map((question, index) => {
    const answer = question.formalAnswerText?.trim() || ''
    const round = [...(question.rounds ?? [])].reverse().find((item) => item.status !== 'DETACHED')
    const draft = answer ? '' : round?.answerText?.trim() || ''
    return { id: question.id, ordinal: index + 1, text: question.text, answer, draft }
  }))
const shown = computed(() => entries.value.filter((entry) => entry.answer || entry.draft))
const unanswered = computed(() => entries.value.length - shown.value.length)
</script>

<template>
  <section class="record-preview" aria-label="正本实时预览">
    <header class="record-preview-head">
      <p v-if="unit" class="record-preview-unit">{{ unit }}</p>
      <h1>询问笔录</h1>
    </header>

    <div class="record-preview-meta">
      <p v-for="(line, index) in meta" :key="index">
        <span v-for="[label, value] in line" :key="label">{{ label }}：<em :class="{ 'is-empty': !value }">{{ value || '未填写' }}</em></span>
      </p>
    </div>

    <ol class="record-preview-body">
      <li v-for="entry in shown" :key="entry.id" :data-question-id="entry.id" :class="entry.answer ? 'is-recorded' : 'is-draft'">
        <p class="record-preview-tag">
          <template v-if="entry.answer">Q{{ entry.ordinal }} · <Check :size="13" aria-hidden="true" />已入正本</template>
          <template v-else>Q{{ entry.ordinal }} · 待摘入（以下为录音转写草稿）</template>
        </p>
        <p class="record-preview-q"><b>问：</b>{{ entry.text }}</p>
        <p v-if="entry.answer" class="record-preview-a"><b>答：</b>{{ entry.answer }}</p>
        <div v-else class="record-preview-draft">
          <small>← 来自 Q{{ entry.ordinal }} · 录音转写草稿，可在左栏修改 · 摘入即落位本段</small>
          <p class="record-preview-a"><b>答：</b>{{ entry.draft }}</p>
          <button type="button" :disabled="busy || locked" @click="emit('commit', entry.id, entry.draft)">摘入正本<ArrowRight :size="15" aria-hidden="true" /></button>
        </div>
      </li>
    </ol>
    <p v-if="!shown.length" class="record-preview-empty">尚无作答内容 · 在左栏点题卡作答后，回答会实时出现在这里</p>
    <p v-else-if="unanswered" class="record-preview-empty">另有 {{ unanswered }} 题未作答 · 作答并摘入后进入正本</p>
  </section>
</template>

<style scoped>
.record-preview { display: flex; flex-direction: column; gap: var(--space-4); min-height: 0; padding: var(--space-5) var(--space-6) var(--space-8); overflow: auto; background: var(--paper-bg); color: var(--paper-ink); font-family: var(--font-serif); }
.record-preview-head { padding-bottom: var(--space-2); border-bottom: 2px solid var(--paper-ink); }
.record-preview-unit { margin: 0; font-size: var(--text-lg); }
.record-preview-head h1 { margin: var(--space-1) 0 0; font-size: var(--text-3xl); font-weight: 600; letter-spacing: 8px; }
.record-preview-meta { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; padding-bottom: var(--space-3); border-bottom: 1px solid var(--paper-rule); font-size: var(--text-base); line-height: 1.7; }
.record-preview-meta p { display: flex; flex-wrap: wrap; column-gap: var(--space-6); margin: 0; }
.record-preview-meta em { font-style: normal; }
.record-preview-meta em.is-empty { color: var(--paper-muted); }
.record-preview-body { display: flex; flex-direction: column; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.record-preview-body li { border-radius: var(--radius-sm); }
.record-preview-tag { display: flex; align-items: center; gap: var(--space-1); margin: 0; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 600; }
.is-recorded .record-preview-tag { color: var(--primary-600); }
.is-draft .record-preview-tag { color: var(--warning-700); }
.record-preview-q, .record-preview-a { margin: var(--space-1) 0 0; font-size: var(--text-lg); line-height: 1.8; }
.record-preview-q b, .record-preview-a b { font-weight: 600; }
.record-preview-draft { display: flex; flex-direction: column; gap: var(--space-1); margin-top: var(--space-2); padding: var(--space-3) var(--space-4); border: 1px dashed var(--primary-500); border-radius: var(--radius-sm); }
.record-preview-draft small { color: var(--primary-600); font-family: var(--font-sans); font-size: var(--text-xs); }
.record-preview-draft .record-preview-a { color: var(--paper-muted); }
.record-preview-draft button { display: inline-flex; align-self: flex-start; align-items: center; gap: var(--space-1); min-height: 44px; margin-top: var(--space-2); padding: 0 var(--space-5); border: 0; border-radius: var(--radius-sm); background: var(--primary-600); color: var(--surface); font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 600; }
.record-preview-empty { margin: 0; color: var(--paper-muted); font-family: var(--font-sans); font-size: var(--text-sm); }
</style>
