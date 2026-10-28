<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight } from '@lucide/vue'
import type { FactItem } from '../types/interrogation'
import { factCoverage } from '../utils/factCoverage'

/** 正本上方的要素覆盖条（样板 P07）：覆盖进度 + 最多 3 个缺项，点「补齐缺项」回到左栏对应题卡。 */
const props = defineProps<{ facts: FactItem[] }>()
const emit = defineEmits<{ fill: [] }>()

const coverage = computed(() => factCoverage(props.facts))
const chips = computed(() => coverage.value.missing.slice(0, 3))
const extra = computed(() => coverage.value.missing.length - chips.value.length)
</script>

<template>
  <div class="coverage-bar record-no-print" role="status">
    <span class="coverage-summary">依据模板 · {{ coverage.total }} 项要素 · 已覆盖 {{ coverage.covered }}/{{ coverage.total }}</span>
    <span v-for="item in chips" :key="item.key" class="coverage-chip" :class="`is-${item.status}`">{{ item.label }} · {{ item.status === 'missing' ? '未获取' : '待补' }}</span>
    <span v-if="extra > 0" class="coverage-chip">+{{ extra }}</span>
    <button v-if="coverage.missing.length" type="button" class="coverage-fill" @click="emit('fill')">补齐缺项<ArrowRight :size="14" aria-hidden="true" /></button>
  </div>
</template>

<style scoped>
.coverage-bar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--line-200); background: var(--surface-sunken); font-size: var(--text-xs); }
.coverage-summary { color: var(--primary-600); font-weight: 600; }
.coverage-chip { padding: 3px var(--space-2); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--ink-500); }
.coverage-chip.is-pending { border-color: var(--warning-600); background: var(--warning-100); color: var(--warning-700); }
.coverage-fill { display: inline-flex; align-items: center; gap: var(--space-1); margin-left: auto; min-height: 32px; padding: 0 var(--space-3); border: 1px solid var(--primary-500); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-xs); font-weight: 600; }
</style>
