<script setup lang="ts">
import { computed } from 'vue'
import { Check } from '@lucide/vue'
import type { FlowStepKey, FlowStepMeta } from '../flow/steps'

const props = defineProps<{
  steps: readonly FlowStepMeta[]
  current: FlowStepKey
  completed: FlowStepKey[]
  reachable: FlowStepKey[]
}>()

const emit = defineEmits<{ select: [key: FlowStepKey] }>()

const currentIndex = computed(() => props.steps.findIndex((step) => step.key === props.current))

function stateOf(key: FlowStepKey, index: number) {
  if (key === props.current) return 'active'
  if (!props.reachable.includes(key)) return 'locked'
  if (props.completed.includes(key)) return 'done'
  return index < currentIndex.value ? 'visited' : 'todo'
}

function canSelect(key: FlowStepKey) {
  return key === props.current || props.reachable.includes(key)
}

function select(key: FlowStepKey) {
  if (!canSelect(key)) return
  if (key === props.current) return
  emit('select', key)
}
</script>

<template>
  <nav class="step-bar" aria-label="办理步骤">
    <ol class="step-list">
      <li v-for="(step, index) in steps" :key="step.key" class="step-item">
        <button
          type="button"
          class="step-button"
          :class="`is-${stateOf(step.key, index)}`"
          :aria-current="step.key === current ? 'step' : undefined"
          :aria-label="step.title"
          :aria-disabled="canSelect(step.key) ? undefined : 'true'"
          :title="canSelect(step.key) ? step.hint : `完成前一步后才能进入${step.title}`"
          @click="select(step.key)"
        >
          <span class="step-index" aria-hidden="true">{{ step.ordinal }}</span>
          <span class="step-title">{{ step.title }}</span>
          <Check v-if="stateOf(step.key, index) === 'done'" class="step-check" :size="14" :stroke-width="2.5" aria-hidden="true" />
        </button>
        <span v-if="index < steps.length - 1" class="step-divider" aria-hidden="true">→</span>
      </li>
    </ol>

    <div class="step-meta">
      <slot />
    </div>
    <div class="step-actions">
      <slot name="actions" />
    </div>
  </nav>
</template>

<style scoped>
/* 样板步骤条：浅底横条，序号与标题连写，完成项绿色带 ✓，当前项蓝色实心胶囊，项间用 → 连接 */
.step-bar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-height: var(--height-stepbar);
  padding: 0 var(--space-8);
  background: var(--line-100);
  flex: 0 0 auto;
}

.step-list {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.step-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-height: 32px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--ink-500);
  font-size: var(--text-base);
  line-height: 1;
  white-space: nowrap;
  transition: color 0.16s ease, background-color 0.16s ease;
}

.step-button:hover:not(.is-active):not(.is-locked) {
  background: var(--primary-50);
}

.step-button.is-active {
  background: var(--primary-600);
  color: var(--surface);
}

.step-button.is-done,
.step-button.is-done .step-check {
  color: var(--success-700);
}

.step-button.is-locked {
  color: var(--ink-400);
  cursor: not-allowed;
}

.step-divider {
  color: var(--ink-300);
  font-size: var(--text-base);
  line-height: 1;
  user-select: none;
}

.step-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-left: auto;
  min-width: 0;
  color: var(--ink-500);
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.step-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
}

.step-actions:empty {
  display: none;
}

@media (max-width: 1280px) {
  .step-meta {
    display: none;
  }

  .step-actions {
    margin-left: auto;
  }
}

/* 1280 屏上步骤条要同时容纳会话控制与「定稿并校验」：非当前步骤只留序号，名称保留在 aria-label / title 中 */
@media (max-width: 1440px) {
  .step-button:not(.is-active) .step-title {
    display: none;
  }
}
</style>
