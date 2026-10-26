<script setup lang="ts">
import { Lock } from '@lucide/vue'

/**
 * 锁屏遮罩（样板 P34）：民警手动点「锁定面板」触发，不设无操作超时；
 * 解锁须重新验证身份。认证尚未接入，解锁入口回到民警验证页。
 */
const emit = defineEmits<{ unlock: [] }>()
</script>

<template>
  <main class="lock-screen" role="dialog" aria-modal="true" aria-labelledby="lock-title">
    <section class="lock-card">
      <Lock :size="28" aria-hidden="true" />
      <h1 id="lock-title">面板已锁定</h1>
      <p>锁屏由民警手动触发 · 解锁需重新验证身份并回到原页面</p>
      <button type="button" @click="emit('unlock')">民警验证解锁</button>
    </section>
  </main>
</template>

<style scoped>
.lock-screen { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: var(--space-6); background: var(--navy-900); }
.lock-card { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-3); width: min(480px, 100%); padding: var(--space-8); border-radius: var(--radius-lg); background: var(--navy-800); color: var(--surface); }
.lock-card h1 { margin: 0; font-size: var(--text-2xl); font-weight: 650; }
.lock-card p { margin: 0; color: var(--primary-200); font-size: var(--text-sm); }
.lock-card button { min-height: 48px; padding: 0 var(--space-6); border: 0; border-radius: var(--radius-md); background: var(--primary-500); color: var(--surface); font-size: var(--text-md); font-weight: 600; }
</style>
