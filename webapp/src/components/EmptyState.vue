<script setup lang="ts">
/**
 * 全局状态 · 空 / 待接入 / 加载失败（样板附录 B P34）
 *
 * - empty：没有数据，操作按钮由使用方放进默认插槽（如「清空筛选条件」）
 * - pending：界面已就位、后端能力尚未接入，固定提示「功能待接入」，不给任何操作
 * - error：加载失败，提供「重试」
 */
withDefaults(defineProps<{
  kind?: 'empty' | 'pending' | 'error'
  title?: string
  description?: string
}>(), { kind: 'empty', title: '', description: '' })

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <section class="empty-state" :class="`is-${kind}`" :role="kind === 'error' ? 'alert' : 'status'">
    <div class="empty-state-box">
      <strong>{{ title || (kind === 'error' ? '加载失败' : kind === 'pending' ? '功能待接入' : '暂无记录') }}</strong>
      <p v-if="kind === 'pending'">功能待接入 · 界面已就位，数据与操作将在后端能力接入后开放</p>
      <p v-else-if="description">{{ description }}</p>
    </div>
    <div v-if="kind === 'error'" class="empty-state-actions">
      <button type="button" class="empty-state-button" @click="emit('retry')">重试</button>
    </div>
    <div v-else-if="kind === 'empty' && $slots.default" class="empty-state-actions">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.empty-state { display: flex; flex-direction: column; gap: var(--space-4); }
.empty-state-box { display: grid; place-content: center; gap: var(--space-2); min-height: 150px; padding: var(--space-6); border-radius: var(--radius-md); background: var(--surface-sunken); text-align: center; }
.empty-state-box strong { color: var(--ink-900); font-size: var(--text-md); font-weight: 600; }
.empty-state-box p { margin: 0; color: var(--ink-400); font-size: var(--text-sm); }
.is-error .empty-state-box { background: var(--danger-100); }
.is-error .empty-state-box strong,
.is-error .empty-state-box p { color: var(--danger-600); }
.empty-state-actions { display: flex; gap: var(--space-2); }
.empty-state-button,
.empty-state-actions :slotted(button) { min-height: 40px; padding: 0 var(--space-4); border: 0; border-radius: var(--radius-sm); background: var(--primary-600); color: var(--surface); font-size: var(--text-sm); font-weight: 600; }
</style>
