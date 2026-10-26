<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, CircleAlert, CircleDashed, ShieldCheck } from '@lucide/vue'
import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * 定稿校验 · 左栏
 *
 * 样板里这一步是"核对要素 → 逐项打勾 → 冻结"：先看哪些要素还没拿到，
 * 再看定稿前必须确认的几件事，最后才允许冻结。冻结后笔录只读。
 */
const props = defineProps<{
  facts: FactItem[]
  questions: FormalQuestion[]
  checks: boolean[]
  blockReason: string
  busy: boolean
  frozen: boolean
  unresolvedFragments: number
  unresolvedQa: number
}>()

const emit = defineEmits<{
  check: [index: number, checked: boolean]
  freeze: []
}>()

const checkLabels = [
  '姓名、证件号码已与证件原件核对',
  '询问时间、地点及询问人、记录人信息已核对',
  '说话人身份、问答归属与文字已人工复核',
  '录音归档、转写与问答处理状态已检查',
  '已查看打印预览并核对版面',
]

const remainingChecks = computed(() => checkLabels.filter((_, index) => !props.checks[index]).length)

/** 要素核对：优先展示尚未确认的事实，已确认的收在后面 */
const factGroups = computed(() => {
  const items = props.facts.filter((item) => item.value && item.value !== '未录入')
  const order = { missing: 0, conflict: 1, pending: 2, confirmed: 3 } as const
  const sorted = [...items].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3))
  return {
    confirmed: items.filter((item) => item.status === 'confirmed').length,
    pending: items.filter((item) => item.status === 'pending').length,
    missing: items.filter((item) => item.status === 'missing').length,
    conflict: items.filter((item) => item.status === 'conflict').length,
    items: sorted.slice(0, 8),
  }
})

const coverage = computed(() => {
  const total = props.questions.length
  const answered = props.questions.filter((question) => question.formalAnswerText?.trim()).length
  return { total, answered, unanswered: total - answered }
})

function statusMeta(status: FactItem['status']) {
  if (status === 'confirmed') return { label: '已确认', cls: 'is-ok', icon: CheckCircle2 }
  if (status === 'missing') return { label: '未获取', cls: 'is-missing', icon: CircleDashed }
  if (status === 'conflict') return { label: '有冲突', cls: 'is-conflict', icon: CircleAlert }
  return { label: '待补', cls: 'is-pending', icon: CircleAlert }
}
</script>

<template>
  <section class="review-checklist" aria-label="定稿校验">
    <article class="review-card">
      <header>
        <h2>核心要素核对</h2>
        <div class="review-counts">
          <span class="is-ok">已确认 {{ factGroups.confirmed }}</span>
          <span class="is-pending">待补 {{ factGroups.pending }}</span>
          <span class="is-missing">未获取 {{ factGroups.missing }}</span>
        </div>
      </header>
      <p class="review-note">未获取的要素会如实标注「未获取」写入笔录；定稿后可在案件详情补录。</p>

      <ul v-if="factGroups.items.length" class="review-fact-list">
        <li v-for="item in factGroups.items" :key="item.key">
          <span class="review-fact-label">{{ item.label }}</span>
          <span class="review-fact-value">{{ item.value }}</span>
          <span class="review-fact-state" :class="statusMeta(item.status).cls">{{ statusMeta(item.status).label }}</span>
        </li>
      </ul>
      <p v-else class="review-empty">尚未录入核心要素，请先回到建档补充身份信息。</p>

      <p class="review-coverage">
        问答覆盖：{{ coverage.answered }} / {{ coverage.total }} 题已成文<template v-if="coverage.unanswered">，{{ coverage.unanswered }} 题未获取</template>
      </p>
      <p v-if="unresolvedFragments || unresolvedQa" class="review-pending-work">
        还有 {{ unresolvedFragments }} 条转写未确认、{{ unresolvedQa }} 组问答待处理
      </p>
    </article>

    <article class="review-card">
      <header>
        <ShieldCheck :size="18" aria-hidden="true" />
        <h2>定稿前检查</h2>
        <span class="review-remaining">{{ remainingChecks ? `剩 ${remainingChecks} 项` : '已全部确认' }}</span>
      </header>

      <label v-for="(label, index) in checkLabels" :key="label" class="review-check" :class="{ checked: checks[index] }">
        <input type="checkbox" :checked="checks[index]" :disabled="busy || frozen" @change="emit('check', index, ($event.target as HTMLInputElement).checked)" />
        <span>{{ label }}</span>
      </label>

      <button type="button" class="review-freeze" :disabled="busy || frozen || !!blockReason" @click="emit('freeze')">
        {{ frozen ? '笔录已冻结' : busy ? '处理中…' : '确认定稿并冻结' }}
      </button>
      <p v-if="blockReason && !frozen" class="review-block" role="status">{{ blockReason }}</p>
      <p class="review-note">冻结后笔录不可再编辑，签名与捺印在「⑤ 签署归档」完成。</p>
    </article>
  </section>
</template>

<style scoped>
.review-checklist {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
  overflow: auto;
  padding: var(--space-3);
  background: var(--surface-sunken);
}

.review-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--line-200);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.review-card > header { display: flex; align-items: center; gap: var(--space-2); }
.review-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 600; }

.review-counts { display: flex; gap: var(--space-2); margin-left: auto; font-size: var(--text-xs); }
.review-counts span { padding: 2px 8px; border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-400); }
.review-counts .is-ok { background: var(--success-100); color: var(--success-700); }
.review-counts .is-pending { background: var(--warning-100); color: var(--warning-700); }
.review-counts .is-missing { background: var(--surface-muted); color: var(--ink-400); }

.review-note { margin: 0; color: var(--ink-400); font-size: var(--text-xs); line-height: 1.7; }

.review-fact-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 1px; background: var(--line-100); }
.review-fact-list li {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  font-size: var(--text-sm);
}
.review-fact-label { color: var(--ink-400); }
.review-fact-value { color: var(--ink-700); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.review-fact-state { padding: 1px 8px; border-radius: var(--radius-pill); font-size: var(--text-xs); background: var(--surface-muted); color: var(--ink-400); }
.review-fact-state.is-ok { background: var(--success-100); color: var(--success-700); }
.review-fact-state.is-pending, .review-fact-state.is-conflict { background: var(--warning-100); color: var(--warning-700); }
.review-fact-state.is-missing { background: var(--surface-muted); color: var(--ink-400); }

.review-empty { margin: 0; padding: var(--space-3); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-300); font-size: var(--text-sm); }
.review-coverage { margin: 0; color: var(--ink-500); font-size: var(--text-sm); }
.review-pending-work { margin: 0; color: var(--warning-700); font-size: var(--text-sm); }

.review-remaining { margin-left: auto; color: var(--ink-400); font-size: var(--text-xs); }

.review-check {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 40px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--ink-700);
  font-size: var(--text-sm);
  cursor: pointer;
}
.review-check:hover { background: var(--surface-sunken); }
.review-check input { width: 18px; height: 18px; accent-color: var(--primary-600); }
.review-check.checked { color: var(--success-700); }

.review-freeze {
  width: 100%;
  min-height: 46px;
  margin-top: var(--space-2);
  border: 0;
  border-radius: var(--radius-md);
  background: var(--primary-600);
  color: var(--surface);
  font-size: var(--text-base);
  font-weight: 600;
}
.review-freeze:hover:not(:disabled) { background: var(--primary-700); }
.review-freeze:disabled { background: var(--surface-muted); color: var(--ink-300); cursor: not-allowed; }

.review-block { margin: 0; padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-xs); line-height: 1.6; }
</style>
