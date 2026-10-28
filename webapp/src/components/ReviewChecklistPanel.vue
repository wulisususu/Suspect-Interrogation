<script setup lang="ts">
import { computed } from 'vue'
import type { CaseSummary, FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { coreFacts } from '../utils/factCoverage'
import type { ReviewAutoCheck } from '../utils/reviewChecks'

/**
 * ④ 定稿校验 · 左栏（样板 P13 / 状态 C）
 *
 * 核心要素核对（已确认 / 待补 / 未获取）+ 定稿前检查。检查项只提示、不代改，
 * 判断权在民警；只有后端必然拒绝的情况（blockReason）才阻止确认定稿。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  questions: FormalQuestion[]
  templateTitle: string
  blockReason: string
  frozen: boolean
  unresolvedFragments: number
  unresolvedQa: number
  autoChecks?: ReviewAutoCheck[]
}>()

type ElementState = 'confirmed' | 'pending' | 'missing'
const STATE_LABEL: Record<ElementState, string> = { confirmed: '已确认 ✓', pending: '待补', missing: '未获取' }

/** 当事人身份证号 + 模板核心要素，未确认的排在已确认之后、未获取放最后（与样板一致）。 */
const elements = computed(() => {
  const identity = { key: 'id-number', label: '当事人身份证号', state: (props.summary.idNumber ? 'confirmed' : 'pending') as ElementState }
  const core = coreFacts(props.facts).map((item) => ({
    key: item.key,
    label: item.label,
    state: (item.status === 'confirmed' ? 'confirmed' : item.status === 'missing' ? 'missing' : 'pending') as ElementState,
  }))
  const order: Record<ElementState, number> = { confirmed: 0, pending: 1, missing: 2 }
  return [identity, ...core].sort((a, b) => order[a.state] - order[b.state])
})
const counts = computed(() => ({
  confirmed: elements.value.filter((item) => item.state === 'confirmed').length,
  pending: elements.value.filter((item) => item.state === 'pending').length,
  missing: elements.value.filter((item) => item.state === 'missing').length,
}))

const drafts = computed(() => props.questions.filter((question) => question.active !== false && !question.formalAnswerText?.trim()
  && question.rounds?.some((round) => round.status !== 'DETACHED' && round.answerText?.trim())).length)

type CheckState = 'pass' | 'pending' | 'unavailable'
const checks = computed<{ key: string; state: CheckState; text: string }[]>(() => {
  const auto = props.autoChecks ?? []
  const find = (key: string) => auto.find((item) => item.key === key)
  const elementsCheck = find('elements')
  const signers = find('signers')
  const list: { key: string; state: CheckState; text: string }[] = [
    { key: 'template', state: 'pass', text: `笔录格式与《${props.templateTitle}》模板一致` },
    { key: 'identity', state: props.summary.idNumber && props.summary.suspectName ? 'pass' : 'pending', text: '身份信息与建档核对一致' },
  ]
  if (elementsCheck) list.push({ key: 'elements', state: elementsCheck.state, text: `模板要素 · ${elementsCheck.detail}` })
  if (signers) list.push({ key: 'signers', state: signers.state, text: `签署人数与身份 · ${signers.detail}` })
  for (const key of ['timeline', 'homophone']) {
    const item = find(key)
    if (item) list.push({ key, state: item.state, text: `${item.title}${item.state === 'unavailable' ? '（待接入）' : ''}` })
  }
  if (drafts.value) list.push({ key: 'drafts', state: 'pending', text: `${drafts.value} 条录音回答尚未摘入正本，未摘入的不会进入笔录` })
  if (props.unresolvedFragments) list.push({ key: 'fragments', state: 'pending', text: `${props.unresolvedFragments} 条转写片段未处理（需确认或丢弃后才能定稿）` })
  if (props.unresolvedQa) list.push({ key: 'qa', state: 'pending', text: `${props.unresolvedQa} 组问答待处置（需处置后才能定稿）` })
  return list
})
const CHECK_MARK: Record<CheckState, string> = { pass: '✓', pending: '!', unavailable: '○' }
</script>

<template>
  <section class="review-checklist" aria-label="定稿校验">
    <header class="review-checklist-head">
      <strong>核心要素核对</strong>
      <span>已确认 {{ counts.confirmed }} · 待补 {{ counts.pending }} · 未获取 {{ counts.missing }}</span>
    </header>
    <ul class="review-elements">
      <li v-for="item in elements" :key="item.key" :class="`is-${item.state}`">
        <span>{{ item.label }}</span><i aria-hidden="true">·</i><span>{{ STATE_LABEL[item.state] }}</span>
      </li>
    </ul>
    <p class="review-note">未获取项将以「未获取」如实记入笔录；定稿并归档后可在案件详情补录</p>

    <h3>定稿前检查</h3>
    <ul class="review-checks">
      <li v-for="item in checks" :key="item.key" :class="`is-${item.state}`"><b aria-hidden="true">{{ CHECK_MARK[item.state] }}</b><span>{{ item.text }}</span></li>
    </ul>

    <p v-if="frozen" class="review-block is-done">笔录已冻结，可进入 ⑤ 签署归档</p>
    <p v-else-if="blockReason" class="review-block" role="status">{{ blockReason }}</p>
  </section>
</template>

<style scoped>
.review-checklist { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; padding: var(--space-6) var(--space-8); overflow: auto; border-radius: var(--radius-lg); background: var(--surface); }
.review-checklist-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-4); }
.review-checklist-head strong { color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.review-checklist-head span { color: var(--ink-900); font-size: var(--text-lg); font-weight: 600; }
.review-elements, .review-checks { display: flex; flex-direction: column; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.review-elements li { display: flex; gap: var(--space-3); font-size: var(--text-md); }
.review-elements i { font-style: normal; }
.review-elements .is-confirmed { color: var(--success-700); }
.review-elements .is-pending { color: var(--warning-700); }
.review-elements .is-missing { color: var(--ink-400); }
.review-note { margin: 0; color: var(--ink-400); font-size: var(--text-xs); }
.review-checklist h3 { margin: var(--space-2) 0 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 650; }
.review-checks li { display: flex; gap: var(--space-3); font-size: var(--text-md); }
.review-checks b { flex: 0 0 16px; font-weight: 600; }
.review-checks .is-pass { color: var(--success-700); }
.review-checks .is-pending { color: var(--warning-700); }
.review-checks .is-unavailable { color: var(--ink-400); }
.review-block { margin: var(--space-2) 0 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-sm); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-sm); }
.review-block.is-done { background: var(--success-100); color: var(--success-700); }
</style>
