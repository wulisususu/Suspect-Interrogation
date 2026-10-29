<script setup lang="ts">
/**
 * 民警身份验证（真实登录）
 *
 * 后端已完成警号+密码登录：成功后下发 HttpOnly 会话 Cookie，10 分钟内免验，
 * 可手动锁定/解锁。本页只负责录入与跳转，不在浏览器里保存密码或伪造校验。
 */
import { onMounted, ref } from 'vue'
import { fetchAuthSession, loginOfficer } from '../api/officers'

const emit = defineEmits<{ back: []; authenticated: [] }>()

const officerId = ref('')
const password = ref('')
const feedback = ref('')
const busy = ref(false)
const configured = ref(true)
const checking = ref(true)

onMounted(async () => {
  try {
    const session = await fetchAuthSession()
    configured.value = session.configured
    if (session.configured && session.authenticated && !session.locked) {
      emit('authenticated')
    }
  } catch {
    // 会话探测失败不阻断手动登录
  } finally {
    checking.value = false
  }
})

async function submitLogin() {
  if (busy.value) return
  feedback.value = ''
  busy.value = true
  try {
    await loginOfficer(officerId.value.trim(), password.value)
    password.value = ''
    emit('authenticated')
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '身份验证失败'
  } finally {
    password.value = ''
    busy.value = false
  }
}
</script>

<template>
  <main class="login-preview-page">
    <section class="login-card" aria-labelledby="login-title">
      <h1 id="login-title">民警身份验证</h1>
      <p class="login-subtitle">管理功能仅限民警使用，验证身份后进入管理面板</p>
      <p v-if="!checking && !configured" class="login-warning">
        尚未配置民警名录。请部署人员在板端执行
        <code>python -m app.auth.provision --badge-number &lt;警号&gt; --name &lt;姓名&gt; --unit &lt;单位&gt; --admin</code>
        后再登录。
      </p>
      <form class="login-form" autocomplete="off" @submit.prevent="submitLogin">
        <label class="sr-only" for="login-officer">民警警号</label>
        <input id="login-officer" v-model.trim="officerId" inputmode="numeric" name="username" autocomplete="username" placeholder="民警警号" required />
        <label class="sr-only" for="login-password">登录密码</label>
        <input id="login-password" v-model="password" type="password" name="current-password" autocomplete="current-password" placeholder="密码" required />
        <div class="login-actions">
          <button type="button" class="login-secondary" @click="emit('back')">取消</button>
          <button class="login-primary" type="submit" :disabled="busy || !configured">{{ busy ? '验证中…' : '验证并进入' }}</button>
        </div>
      </form>
      <p v-if="feedback" class="login-feedback" role="alert">{{ feedback }}</p>
      <p class="login-note">验证通过后 10 分钟内免验 · 收起与锁定均由民警手动触发</p>
    </section>
  </main>
</template>

<style scoped>
.login-preview-page { min-height: 100vh; min-width: 320px; display: grid; place-items: center; padding: var(--space-10) var(--space-5); background: var(--navy-700); }
.login-card { width: min(452px, 100%); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.login-card h1 { margin: 0 0 var(--space-2); color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.login-subtitle { margin: 0 0 var(--space-4); color: var(--ink-500); font-size: var(--text-xs); }
.login-warning { margin: 0 0 var(--space-3); padding: var(--space-3); border-radius: var(--radius-md); background: var(--warning-50); color: var(--warning-700); font-size: var(--text-xs); line-height: 1.6; }
.login-warning code { display: block; margin-top: 6px; font-size: var(--text-xs); word-break: break-all; }
.login-form { display: flex; flex-direction: column; gap: var(--space-3); }
.login-form input { min-height: 46px; padding: 0 var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-800); font-size: var(--text-sm); }
.login-actions { display: flex; gap: var(--space-2); }
.login-primary, .login-secondary { flex: 1; min-height: 46px; border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: 600; cursor: pointer; }
.login-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.login-primary:disabled { opacity: 0.6; cursor: default; }
.login-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.login-feedback { margin: var(--space-3) 0 0; color: var(--danger-700); font-size: var(--text-xs); }
.login-note { margin: var(--space-4) 0 0; color: var(--ink-400); font-size: var(--text-xs); }
</style>
