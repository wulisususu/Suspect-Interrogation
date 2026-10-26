<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{ back: [] }>()
const officerId = ref('')
const password = ref('')
const feedback = ref('')

function submitLogin() {
  // 此页面仅实现设计稿的前端界面，不在浏览器伪造密码校验或用户会话。
  password.value = ''
  feedback.value = '当前系统尚未接入警号密码认证接口。登录界面已完成，但正式认证尚不可用。'
}
</script>

<template>
  <main class="login-preview-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-mark" aria-hidden="true">警</div>
      <h1 id="login-title">嫌疑人询问系统</h1>
      <p class="login-subtitle">江北分局 · 刑侦大队 · 内网专用终端</p>

      <form class="login-form" autocomplete="off" @submit.prevent="submitLogin">
        <label for="login-officer">民警警号</label>
        <input
          id="login-officer"
          v-model.trim="officerId"
          inputmode="numeric"
          name="username"
          autocomplete="username"
          placeholder="请输入民警警号"
          required
        />
        <label for="login-password">登录密码</label>
        <input
          id="login-password"
          v-model="password"
          type="password"
          name="password"
          autocomplete="current-password"
          placeholder="请输入登录密码"
          required
        />
        <button class="login-primary" type="submit">登录</button>
      </form>

      <p v-if="feedback" class="login-feedback" role="status">{{ feedback }}</p>
      <p class="login-note">本系统为公安内网专用设备，所有操作需留痕可追溯</p>
      <div class="preview-warning">
        <strong>前端预览模式</strong>
        <span>尚未启用真实身份认证，填写内容不会上传或用于授权。</span>
        <button type="button" @click="emit('back')">返回案件管理（原有无认证入口）</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-preview-page { min-height: 100vh; min-width: 320px; display: grid; place-items: center; padding: 40px 20px; background: var(--surface-sunken); color: var(--navy-900); font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }
.login-card { width: min(408px, 100%); padding: 35px; text-align: center; background: var(--surface); border-radius: 13px; box-shadow: 0 8px 25px rgba(16,34,65,.025); }
.login-mark { display: grid; place-items: center; width: 52px; height: 52px; margin: 0 auto 12px; border-radius: 13px; background: var(--primary-700); color: var(--surface); font-size: var(--text-2xl); font-weight: 700; }
.login-card h1 { margin: 0 0 6px; font-size: var(--text-xl); letter-spacing: .025em; font-weight: 750; }
.login-subtitle { margin: 0 0 30px; color: var(--ink-300); font-size: var(--text-xs); }
.login-form { display: flex; flex-direction: column; text-align: left; gap: 7px; }
.login-form label { margin-top: 2px; color: var(--ink-500); font-size: var(--text-xs); font-weight: 650; }
.login-form input { width: 100%; height: 43px; padding: 0 13px; margin-bottom: 12px; background: var(--surface-sunken); border: 1px solid transparent; border-radius: 7px; outline: none; color: var(--navy-900); font-size: var(--text-base); }
.login-form input:focus { border-color: var(--primary-600); box-shadow: 0 0 0 3px rgba(34,82,143,.09); }
.login-primary { height: 43px; margin-top: 1px; border: none; border-radius: 7px; background: var(--primary-600); color: white; font-weight: 700; }
.login-primary:hover { background: var(--primary-700); }
.login-feedback { margin: 14px 0 0; padding: 10px; background: var(--warning-100); border: 1px solid var(--warning-100); border-radius: 7px; color: var(--warning-700); text-align: left; font-size: var(--text-xs); line-height: 1.7; }
.login-note { margin: 20px 0 0; color: var(--ink-400); font-size: var(--text-xs); }
.preview-warning { display: grid; gap: 7px; margin-top: 23px; padding: 12px; border: 1px dashed var(--line-300); border-radius: 8px; background: var(--surface-sunken); color: var(--ink-500); text-align: left; font-size: var(--text-xs); line-height: 1.55; }
.preview-warning strong { color: var(--primary-600); }
.preview-warning button { padding: 8px; border: 1px solid var(--line-300); border-radius: 5px; background: var(--surface); color: var(--primary-700); font-weight: 650; }
@media (max-width: 480px) { .login-card { padding: 25px 20px; } }
</style>
