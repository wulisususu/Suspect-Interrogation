<script setup lang="ts">
import { ChevronLeft, Lock } from '@lucide/vue'

/**
 * 后台管理外壳（样板 P19 顶栏）：深色顶栏 + 返回 + 页面标题，右侧锁定面板。
 * 民警认证尚未接入，顶栏如实标注，不显示伪造的「已验证」身份。
 */
withDefaults(defineProps<{ title: string; backLabel?: string }>(), { backLabel: '返回管理面板' })
const emit = defineEmits<{ back: []; lock: [] }>()
</script>

<template>
  <div class="admin-shell">
    <header class="admin-topbar">
      <button type="button" class="admin-back" @click="emit('back')"><ChevronLeft :size="15" aria-hidden="true" />{{ backLabel }}</button>
      <strong>公安笔录一体机 · 后台管理</strong>
      <span class="admin-title">{{ title }}</span>
      <span class="admin-auth">认证尚未接入</span>
      <button type="button" class="admin-lock" @click="emit('lock')"><Lock :size="14" aria-hidden="true" />锁定面板</button>
    </header>
    <main class="admin-body"><slot /></main>
  </div>
</template>

<style scoped>
.admin-shell { display: flex; flex-direction: column; height: 100vh; background: var(--surface-sunken); }
.admin-topbar { display: flex; align-items: center; gap: var(--space-3); flex: 0 0 auto; min-height: var(--height-topbar); padding: 0 var(--space-6); background: var(--navy-900); color: var(--surface); }
.admin-topbar strong { font-size: var(--text-md); font-weight: 600; }
.admin-title { color: var(--primary-100); font-size: var(--text-sm); }
.admin-back, .admin-lock { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 36px; padding: 0 var(--space-3); border: 0; border-radius: var(--radius-sm); background: rgba(255, 255, 255, 0.1); color: var(--primary-100); font-size: var(--text-xs); }
.admin-auth { margin-left: auto; padding: var(--space-1) var(--space-3); border-radius: var(--radius-pill); background: rgba(255, 255, 255, 0.08); color: var(--warning-100); font-size: var(--text-xs); }
.admin-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: var(--space-6); }
</style>
