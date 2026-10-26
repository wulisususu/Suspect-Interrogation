<script setup lang="ts">
import { ref } from 'vue'

/**
 * 管理权限 · 民警身份验证（样板 P18）
 *
 * 警号密码认证接口尚未接入：本页不在浏览器伪造校验或会话，提交只给出说明；
 * 「进入管理面板（预览 · 未认证）」明确标注未认证，供界面验收使用。
 */
const emit = defineEmits<{ back: []; admin: [] }>()
const officerId = ref('')
const password = ref('')
const feedback = ref('')

function submitLogin() {
  password.value = ''
  feedback.value = '当前系统尚未接入警号密码认证接口。登录界面已完成，但正式认证尚不可用。'
}
</script>

<template>
  <main class="login-preview-page">
    <section class="login-card" aria-labelledby="login-title">
      <h1 id="login-title">民警身份验证</h1>
      <p class="login-subtitle">管理功能仅限民警使用，验证身份后进入管理面板</p>

      <form class="login-form" autocomplete="off" @submit.prevent="submitLogin">
        <label class="sr-only" for="login-officer">民警警号</label>
        <input id="login-officer" v-model.trim="officerId" inputmode="numeric" name="username" autocomplete="username" placeholder="民警警号" required />
        <label class="sr-only" for="login-password">登录密码</label>
        <input id="login-password" v-model="password" type="password" name="password" autocomplete="current-password" placeholder="密码" required />
        <div class="login-actions">
          <button type="button" class="login-secondary" @click="emit('back')">取消</button>
          <button class="login-primary" type="submit">验证并进入</button>
        </div>
      </form>

      <p v-if="feedback" class="login-feedback" role="status">{{ feedback }}</p>
      <p class="login-note">验证通过后 10 分钟内免验 · 收起与锁定均由民警手动触发</p>
      <div class="preview-warning">
        <strong>前端预览模式</strong>
        <span>尚未启用真实身份认证，填写内容不会上传或用于授权。</span>
        <button type="button" @click="emit('admin')">进入管理面板（预览 · 未认证）</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-preview-page { min-height: 100vh; min-width: 320px; display: grid; place-items: center; padding: var(--space-10) var(--space-5); background: var(--navy-700); }
.login-card { width: min(452px, 100%); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.login-card h1 { margin: 0 0 var(--space-2); color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.login-subtitle { margin: 0 0 var(--space-4); color: var(--ink-500); font-size: var(--text-xs); }
.login-form { display: flex; flex-direction: column; gap: var(--space-3); }
.login-form input { width: 100%; height: 44px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-900); font-size: var(--text-base); }
.login-form input:focus { border-color: var(--primary-600); box-shadow: var(--shadow-focus); outline: none; }
.login-actions { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.login-primary, .login-secondary { height: 44px; border-radius: var(--radius-sm); font-size: var(--text-sm); font-weight: 600; }
.login-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.login-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.login-feedback { margin: var(--space-3) 0 0; padding: var(--space-3); border-radius: var(--radius-sm); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-xs); line-height: 1.7; }
.login-note { margin: var(--space-3) 0 0; color: var(--ink-400); font-size: var(--text-xs); }
.preview-warning { display: grid; gap: var(--space-2); margin-top: var(--space-4); padding: var(--space-3); border: 1px dashed var(--line-300); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); line-height: 1.55; }
.preview-warning strong { color: var(--primary-600); }
.preview-warning button { min-height: 40px; border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-700); font-weight: 600; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
