<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { fetchLive } from '../api/health'

const MAX_CONSECUTIVE_FAILURES = 3
const PROBE_TIMEOUT_MS = 3000
const PROBE_INTERVAL_MS = 5000

const phase = ref<'checking' | 'ready' | 'maintenance'>('checking')
const error = ref('')
let timer: number | undefined
let consecutiveFailures = 0
let refreshInFlight = false

async function refresh() {
  if (refreshInFlight) return
  refreshInFlight = true

  const controller = new AbortController()
  let timedOut = false
  const timeout = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, PROBE_TIMEOUT_MS)

  try {
    await fetchLive(controller.signal)
    consecutiveFailures = 0
    error.value = ''
    phase.value = 'ready'
  } catch (cause) {
    consecutiveFailures += 1

    // A single network jitter/AbortController timeout must never unmount an
    // active interrogation workspace. Only sustained process-level liveness
    // failures are allowed to move the global application gate to maintenance.
    if (consecutiveFailures < MAX_CONSECUTIVE_FAILURES) return

    phase.value = 'maintenance'
    error.value = timedOut
      ? '本地后端连续多次响应超时，系统正在自动重试'
      : cause instanceof Error
        ? cause.message
        : '本地后端连续多次无响应，系统正在自动重试'
  } finally {
    window.clearTimeout(timeout)
    refreshInFlight = false
  }
}

onMounted(() => {
  void refresh()
  timer = window.setInterval(() => void refresh(), PROBE_INTERVAL_MS)
})

onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer)
})
</script>

<template>
  <slot v-if="phase === 'ready'" />
  <main v-else class="maintenance-shell" role="status" aria-live="polite">
    <section class="maintenance-card">
      <p class="maintenance-kicker">Linux Kiosk</p>
      <h1>{{ phase === 'checking' ? '系统正在启动' : '系统维护中' }}</h1>
      <p v-if="phase === 'checking'">正在检查本地后端进程状态，请稍候。</p>
      <template v-else>
        <p>本地后端已连续多次无响应。业务页面会在服务恢复后自动返回。</p>
        <p v-if="error" class="maintenance-details">{{ error }}</p>
        <button type="button" @click="refresh">立即重试</button>
      </template>
    </section>
  </main>
</template>

<style scoped>
.maintenance-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  background: var(--surface-sunken);
  color: var(--navy-900);
}
.maintenance-card {
  width: min(620px, 100%);
  padding: 40px;
  border-radius: 18px;
  background: var(--surface);
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.08);
}
.maintenance-kicker {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-500);
}
h1 { margin: 0 0 16px; font-size: 30px; }
p { line-height: 1.7; }
.maintenance-details { color: var(--warning-600); line-height: 1.6; }
button {
  margin-top: 12px;
  border: 0;
  border-radius: 10px;
  padding: 11px 18px;
  background: var(--navy-900);
  color: var(--surface);
  cursor: pointer;
}
</style>
