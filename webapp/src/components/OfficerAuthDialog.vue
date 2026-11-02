<script setup lang="ts">
/**
 * 民警重新验证弹窗
 *
 * 叠加在当前页面之上，不卸载办案页：会话过期时重新登录，面板被锁时解锁
 * （10 分钟免验期内无需密码，过期后输入密码；锁定期间会话失效则改为登录）。
 * 不在浏览器保存密码。
 */
import { computed, ref } from 'vue'
import { loginOfficer, unlockOfficerPanel } from '../api/officers'
import { backendErrorMessage } from '../api/interrogation'
import type { OfficerAuthReason } from '../auth/officerAuth'

const props = defineProps<{ reason: OfficerAuthReason }>()
const emit = defineEmits<{ done: [ok: boolean] }>()

const mode = ref<'login' | 'unlock'>(props.reason === 'locked' ? 'unlock' : 'login')
const badgeNumber = ref('')
const password = ref('')
const needPassword = ref(mode.value === 'login')
const busy = ref(false)
const feedback = ref('')

const title = computed(() => mode.value === 'unlock' ? '面板已锁定' : '请重新验证民警身份')
const hint = computed(() => mode.value === 'unlock'
  ? '解锁后回到当前页面；录音在验证期间继续缓存，解锁后自动续传。'
  : '会话已过期或尚未验证。验证后回到当前页面，录音缓存会自动续传。')

function errorCode(err: unknown): string | undefined {
  return (err as { response?: { data?: { code?: string } } })?.response?.data?.code
}

async function submit() {
  if (busy.value) return
  busy.value = true
  feedback.value = ''
  try {
    if (mode.value === 'login') {
      await loginOfficer(badgeNumber.value.trim(), password.value)
    } else {
      await unlockOfficerPanel(needPassword.value ? password.value : undefined)
    }
    emit('done', true)
  } catch (err) {
    const code = errorCode(err)
    if (mode.value === 'unlock' && code === 'AUTH_REAUTHENTICATION_REQUIRED' && !needPassword.value) {
      needPassword.value = true
      feedback.value = '免验已过期，请输入密码解锁'
    } else if (mode.value === 'unlock' && code === 'AUTH_SESSION_REQUIRED') {
      mode.value = 'login'
      needPassword.value = true
      feedback.value = '会话已失效，请输入警号和密码重新登录'
    } else {
      feedback.value = backendErrorMessage(err)
    }
  } finally {
    password.value = ''
    busy.value = false
  }
}
</script>

<template>
  <div class="officer-auth-backdrop">
    <section class="officer-auth-card" role="dialog" aria-modal="true" aria-labelledby="officer-auth-title">
      <h2 id="officer-auth-title">{{ title }}</h2>
      <p class="officer-auth-hint">{{ hint }}</p>
      <form class="officer-auth-form" autocomplete="off" @submit.prevent="submit">
        <template v-if="mode === 'login'">
          <label class="sr-only" for="officer-auth-badge">民警警号</label>
          <input id="officer-auth-badge" v-model.trim="badgeNumber" inputmode="numeric" autocomplete="username" placeholder="民警警号" required />
        </template>
        <template v-if="needPassword">
          <label class="sr-only" for="officer-auth-password">登录密码</label>
          <input id="officer-auth-password" v-model="password" type="password" autocomplete="current-password" placeholder="密码" required />
        </template>
        <div class="officer-auth-actions">
          <button type="button" class="officer-auth-secondary" :disabled="busy" @click="emit('done', false)">稍后</button>
          <button type="submit" class="officer-auth-primary" :disabled="busy">{{ busy ? '验证中…' : mode === 'unlock' ? '解锁' : '验证' }}</button>
        </div>
      </form>
      <p v-if="feedback" class="officer-auth-feedback" role="alert">{{ feedback }}</p>
    </section>
  </div>
</template>

<style scoped>
.officer-auth-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; padding: var(--space-6); background: rgba(10, 20, 40, 0.72); }
.officer-auth-card { width: min(440px, 100%); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.officer-auth-card h2 { margin: 0 0 var(--space-2); color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.officer-auth-hint { margin: 0 0 var(--space-4); color: var(--ink-500); font-size: var(--text-sm); }
.officer-auth-form { display: flex; flex-direction: column; gap: var(--space-3); }
.officer-auth-form input { min-height: 44px; padding: 0 var(--space-3); border: 1px solid var(--line-200); border-radius: var(--radius-md); font-size: var(--text-md); }
.officer-auth-actions { display: flex; justify-content: flex-end; gap: var(--space-3); }
.officer-auth-primary, .officer-auth-secondary { min-height: 44px; padding: 0 var(--space-5); border-radius: var(--radius-md); font-size: var(--text-md); font-weight: 600; }
.officer-auth-primary { border: 0; background: var(--primary-500); color: var(--surface); }
.officer-auth-secondary { border: 1px solid var(--line-200); background: var(--surface); color: var(--ink-700); }
.officer-auth-feedback { margin: var(--space-3) 0 0; color: var(--danger-600); font-size: var(--text-sm); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
