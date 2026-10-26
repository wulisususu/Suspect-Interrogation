<script setup lang="ts">
import { ref } from 'vue'
import AdminShell from './components/AdminShell.vue'
import EmptyState from './components/EmptyState.vue'
import MaintenanceGate from './components/MaintenanceGate.vue'
import OnScreenKeyboard from './components/OnScreenKeyboard.vue'
import AdminPanelView from './views/AdminPanelView.vue'
import CaseDashboardView from './views/CaseDashboardView.vue'
import KioskHomeView from './views/KioskHomeView.vue'
import LoginView from './views/LoginView.vue'
import InterrogationWorkspace from './views/InterrogationWorkspace.vue'
import SystemSettingsView from './views/SystemSettingsView.vue'
import { parseRootRoute, rootRouteUrl, type AdminPanel, type RootRoute } from './utils/rootRoute'

const route = ref<RootRoute>(parseRootRoute(location.search))

function go(next: RootRoute) {
  route.value = next
  history.replaceState(null, '', rootRouteUrl(location.href, next))
}

const openCase = (caseId: string) => go({ page: 'case', caseId })
const openCases = () => go({ page: 'cases' })
const openSettings = () => go({ page: 'settings' })
const openLogin = () => go({ page: 'login' })
const openHome = () => go({ page: 'home' })
const openAdmin = () => go({ page: 'admin' })
const openPlaceholder = (panel: AdminPanel) => go({ page: 'admin-placeholder', panel })

const ADMIN_TITLES: Record<string, string> = {
  'admin-pending': '未完成办理',
  'admin-audit': '操作日志',
}
</script>

<template>
  <MaintenanceGate>
    <InterrogationWorkspace v-if="route.page === 'case'" :key="route.caseId" :case-id="route.caseId" @back="openCases" />
    <SystemSettingsView v-else-if="route.page === 'settings'" @back="openCases" />
    <LoginView v-else-if="route.page === 'login'" @back="openHome" @admin="openAdmin" />
    <KioskHomeView v-else-if="route.page === 'home'" @start="openCases" @police-entry="openLogin" />
    <AdminShell v-else-if="route.page === 'admin'" title="管理面板" back-label="返回大厅" @back="openHome" @lock="openHome">
      <AdminPanelView
        @cases="openCases"
        @pending="go({ page: 'admin-pending' })"
        @audit="go({ page: 'admin-audit' })"
        @voiceprints="openSettings"
        @placeholder="openPlaceholder"
      />
    </AdminShell>
    <AdminShell v-else-if="route.page !== 'cases'" :title="ADMIN_TITLES[route.page] ?? '后台管理'" @back="openAdmin" @lock="openHome">
      <EmptyState kind="pending" :title="ADMIN_TITLES[route.page] ?? '后台管理'" />
    </AdminShell>
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
          <button type="button" class="voice-entry" @click="openHome">← 返回大厅</button>
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
.case-root-shell { display: flex; flex-direction: column; height: 100vh; width: 100%; min-width: 0; background: var(--surface-sunken); }
.root-navigation { height: 54px; flex: 0 0 54px; display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 0 23px; background: var(--primary-700); color: var(--surface); }
.brand-area, .root-navigation-actions { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-area strong { font-weight: 750; font-size: var(--text-md); white-space: nowrap; }
.shield-mark { width: 24px; height: 27px; display: grid; place-items: center; clip-path: polygon(50% 0, 95% 20%, 90% 72%, 50% 100%, 10% 72%, 5% 20%); background: var(--surface); color: var(--primary-700); font-size: var(--text-md); }
.nav-divider { width: 1px; height: 19px; background: var(--primary-600); }
.nav-department { color: var(--line-300); font-size: var(--text-xs); white-space: nowrap; }
.internal-pill { background: var(--danger-600); color: var(--danger-100); padding: 7px 12px; border-radius: 99px; font-size: var(--text-xs); white-space: nowrap; }
.root-navigation-actions { margin-left: auto; }
.root-navigation-actions button { padding: 7px 11px; background: var(--primary-700); border: 1px solid transparent; border-radius: 8px; color: var(--primary-100); font-size: var(--text-xs); white-space: nowrap; }
.root-navigation-actions button:hover { background: var(--primary-600); }
.root-navigation-actions .login-entry { background: transparent; border-color: var(--primary-600); color: var(--line-300); }
.nav-avatar { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: var(--primary-600); color: var(--surface); font-size: var(--text-xs); }
@media (max-width: 1150px) { .root-navigation { padding: 0 14px; } .nav-department, .internal-pill { display: none; } }
@media (max-width: 720px) { .voice-entry { display: none; } .brand-area strong { font-size: var(--text-sm); } }
</style>
