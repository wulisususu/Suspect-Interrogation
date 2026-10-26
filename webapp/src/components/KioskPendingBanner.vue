<script setup lang="ts">
import { ArrowRight } from '@lucide/vue'

/** 大厅未完成办理提示：一体机面向当事人，只给条数，详情须民警验证后查看（样板 P04）。 */
defineProps<{ count: number }>()
const emit = defineEmits<{ verify: [] }>()
</script>

<template>
  <div class="kiosk-pending" role="status">
    <span class="kiosk-pending-dot" aria-hidden="true"></span>
    <span class="kiosk-pending-text">有 {{ count }} 项未完成办理 · 仅显示条数，验证后展开详情</span>
    <button type="button" class="kiosk-pending-action" @click="emit('verify')">验证并继续<ArrowRight :size="15" aria-hidden="true" /></button>
  </div>
</template>

<style scoped>
.kiosk-pending { display: flex; align-items: center; gap: var(--space-3); min-height: 44px; padding: 0 var(--space-4); border: 1px solid var(--warning-600); border-radius: var(--radius-md); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-sm); }
.kiosk-pending-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warning-600); flex: none; }
.kiosk-pending-text { flex: 1 1 auto; min-width: 0; }
.kiosk-pending-action { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 44px; border: 0; background: transparent; color: var(--warning-700); font-size: var(--text-sm); font-weight: 600; white-space: nowrap; }
</style>
