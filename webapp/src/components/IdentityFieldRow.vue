<script setup lang="ts">
/** 建档字段行：左标签、中间输入控件（插槽）、右侧标注数据来源（样板 P06）。 */
defineProps<{
  label: string
  source: 'CARD' | 'MANUAL' | 'AUTO'
  required?: boolean
  /** 覆盖右侧来源文案，如「下拉选择」「默认当前 · 可改」 */
  sourceText?: string
}>()

const SOURCE_LABEL = { CARD: '身份证读取', MANUAL: '手工补填', AUTO: '自动推算' } as const
</script>

<template>
  <label class="identity-row" :class="`is-${source.toLowerCase()}`">
    <span class="identity-row-label">{{ label }}<b v-if="required" aria-hidden="true">*</b></span>
    <span class="identity-row-control"><slot /></span>
    <span class="identity-row-source">{{ sourceText || SOURCE_LABEL[source] }}</span>
  </label>
</template>

<style scoped>
.identity-row { display: grid; grid-template-columns: 112px minmax(0, 1fr) auto; align-items: center; gap: var(--space-3); min-height: 44px; padding: 0 var(--space-4); border: 1px solid transparent; border-radius: var(--radius-md); background: var(--surface-sunken); }
.identity-row.is-manual { border-color: var(--primary-500); background: var(--surface); }
.identity-row-label { color: var(--ink-400); font-size: var(--text-sm); }
.identity-row-label b { margin-left: 2px; color: var(--danger-600); }
.identity-row-control :slotted(input),
.identity-row-control :slotted(select),
.identity-row-control :slotted(textarea) { width: 100%; min-height: 38px; border: 0; background: transparent; color: var(--ink-900); font: inherit; font-size: var(--text-base); resize: none; }
.identity-row-control :slotted(select) { flex: 0 0 120px; width: 120px; }
.identity-row-source { color: var(--ink-400); font-size: var(--text-xs); white-space: nowrap; }
.identity-row.is-manual .identity-row-source { color: var(--primary-600); }
</style>
