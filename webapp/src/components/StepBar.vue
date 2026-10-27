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
          <span class="step-index" aria-hidden="true">
            <Check v-if="stateOf(step.key, index) === 'done'" :size="13" :stroke-width="3" />
            <template v-else>{{ index + 1 }}</template>
          </span>
          <span class="step-title">{{ step.title }}</span>
        </button>
        <span v-if="index < steps.length - 1" class="step-divider" aria-hidden="true">›</span>
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
.step-bar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-height: var(--height-stepbar);
  padding: 0 var(--space-6);
  background: var(--surface);
  border-bottom: 1px solid var(--line-200);
  flex: 0 0 auto;
}

.step-list {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.step-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--ink-400);
  font-size: var(--text-base);
  line-height: 1;
  white-space: nowrap;
  transition: color 0.16s ease, background-color 0.16s ease, border-color 0.16s ease;
}

.step-button:hover:not(.is-active):not(.is-locked) {
  color: var(--primary-600);
  background: var(--primary-50);
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  border: 1px solid var(--line-300);
  border-radius: 50%;
  color: var(--ink-400);
  font-size: var(--text-xs);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.step-button.is-active {
  color: var(--primary-700);
  background: var(--primary-100);
  font-weight: 600;
}

.step-button.is-active .step-index {
  border-color: var(--primary-600);
  background: var(--primary-600);
  color: var(--surface);
}

.step-button.is-done {
  color: var(--ink-700);
}

.step-button.is-done .step-index {
  border-color: var(--success-600);
  background: var(--success-100);
  color: var(--success-700);
}

.step-button.is-visited {
  color: var(--ink-500);
}

.step-button.is-visited .step-index {
  border-color: var(--primary-200);
  color: var(--primary-600);
}

.step-button.is-locked {
  color: var(--ink-300);
  cursor: not-allowed;
}

.step-button.is-locked .step-index {
  border-color: var(--line-200);
  color: var(--ink-300);
}

.step-divider {
  color: var(--line-300);
  font-size: var(--text-base);
  line-height: 1;
  user-select: none;
}

.step-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-left: var(--space-3);
  min-width: 0;
  color: var(--ink-400);
  font-size: var(--text-sm);
  overflow: hidden;
}

.step-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-left: auto;
  flex: 0 0 auto;
}

@media (max-width: 1280px) {
  .step-meta {
    display: none;
  }
}

/* 1280 屏上步骤条要同时容纳会话控制与「定稿并校验」：非当前步骤只留序号，名称保留在 aria-label / title 中 */
@media (max-width: 1440px) {
  .step-button:not(.is-active) .step-title {
    display: none;
  }
}
</style>
