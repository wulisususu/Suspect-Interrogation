<script setup lang="ts">
import { ref } from 'vue'
import MaintenanceGate from './components/MaintenanceGate.vue'
import OnScreenKeyboard from './components/OnScreenKeyboard.vue'
import CaseDashboardView from './views/CaseDashboardView.vue'
import LoginView from './views/LoginView.vue'
import InterrogationWorkspace from './views/InterrogationWorkspace.vue'
import SystemSettingsView from './views/SystemSettingsView.vue'

type RootPage = 'cases' | 'settings' | 'login'

const params = new URLSearchParams(location.search)
const caseId = ref(params.get('caseId') || '')
const rootPage = ref<RootPage>(
  params.get('view') === 'settings' ? 'settings' : params.get('view') === 'login' ? 'login' : 'cases',
)

function writeLocation() {
  const next = new URL(location.href)
  if (caseId.value) next.searchParams.set('caseId', caseId.value)
  else next.searchParams.delete('caseId')
  if (!caseId.value && rootPage.value === 'settings') next.searchParams.set('view', 'settings')
  else if (!caseId.value && rootPage.value === 'login') next.searchParams.set('view', 'login')
  else next.searchParams.delete('view')
  history.replaceState(null, '', next)
}
function openCase(id: string) {
  rootPage.value = 'cases'
  caseId.value = id
  writeLocation()
}
function backToList() {
  caseId.value = ''
  rootPage.value = 'cases'
  writeLocation()
}
function openSettings() {
  caseId.value = ''
  rootPage.value = 'settings'
  writeLocation()
}
function openLogin() {
  caseId.value = ''
  rootPage.value = 'login'
  writeLocation()
}
</script>

<template>
  <MaintenanceGate>
    <InterrogationWorkspace v-if="caseId" :key="caseId" :case-id="caseId" @back="backToList" />
    <SystemSettingsView v-else-if="rootPage === 'settings'" @back="backToList" />
    <LoginView v-else-if="rootPage === 'login'" @back="backToList" />
    <div v-else class="case-root-shell">
      <nav class="root-navigation" aria-label="系统一级导航">
        <div class="brand-area">
          <span class="shield-mark" aria-hidden="true">★</span>
          <strong>嫌疑人询问系统</strong>
          <span class="nav-divider"></span>
          <span class="nav-department">江北分局 · 刑侦大队</span>
          <span class="internal-pill">● 内网专用终端</span>
        </div>
        <div class="root-navigation-actions">
          <button type="button" class="voice-entry" @click="openSettings">系统设置 · 民警声纹库</button>
          <button type="button" class="login-entry" @click="openLogin">登录页预览</button>
          <span class="nav-avatar" aria-hidden="true">警</span>
        </div>
      </nav>
      <CaseDashboardView @open="openCase" @settings="openSettings" @login="openLogin" />
    </div>
  </MaintenanceGate>
  <OnScreenKeyboard />
</template>

<style scoped>
.case-root-shell { display: flex; flex-direction: column; height: 100vh; width: 100%; min-width: 0; background: #f4f6fb; }
.root-navigation { height: 54px; flex: 0 0 54px; display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 0 23px; background: #19345e; color: #fff; }
.brand-area, .root-navigation-actions { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-area strong { font-weight: 750; font-size: 15px; white-space: nowrap; }
.shield-mark { width: 24px; height: 27px; display: grid; place-items: center; clip-path: polygon(50% 0, 95% 20%, 90% 72%, 50% 100%, 10% 72%, 5% 20%); background: #fff; color: #19345e; font-size: 15px; }
.nav-divider { width: 1px; height: 19px; background: #49658d; }
.nav-department { color: #c3d1e7; font-size: 12px; white-space: nowrap; }
.internal-pill { background: #703d3a; color: #ffd7c7; padding: 7px 12px; border-radius: 99px; font-size: 11px; white-space: nowrap; }
.root-navigation-actions { margin-left: auto; }
.root-navigation-actions button { padding: 7px 11px; background: #254574; border: 1px solid transparent; border-radius: 8px; color: #dfe9fb; font-size: 11px; white-space: nowrap; }
.root-navigation-actions button:hover { background: #31588b; }
.root-navigation-actions .login-entry { background: transparent; border-color: #46638c; color: #bfcde4; }
.nav-avatar { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: #426193; color: #fff; font-size: 12px; }
@media (max-width: 1150px) { .root-navigation { padding: 0 14px; } .nav-department, .internal-pill { display: none; } }
@media (max-width: 720px) { .voice-entry { display: none; } .brand-area strong { font-size: 13px; } }
</style>
