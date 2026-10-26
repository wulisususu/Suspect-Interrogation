<script setup lang="ts">
import { ref } from 'vue'
import AdminShell from './components/AdminShell.vue'
import EmptyState from './components/EmptyState.vue'
import MaintenanceGate from './components/MaintenanceGate.vue'
import OnScreenKeyboard from './components/OnScreenKeyboard.vue'
import AdminAuditView from './views/AdminAuditView.vue'
import AdminCaseDetailView from './views/AdminCaseDetailView.vue'
import AdminPendingView from './views/AdminPendingView.vue'
import AdminPanelView from './views/AdminPanelView.vue'
import CaseDashboardView from './views/CaseDashboardView.vue'
import KioskHomeView from './views/KioskHomeView.vue'
import LoginView from './views/LoginView.vue'
import InterrogationWorkspace from './views/InterrogationWorkspace.vue'
import SystemSettingsView from './views/SystemSettingsView.vue'
import { parseRootRoute, rootRouteUrl, type AdminPanel, type RootRoute } from './utils/rootRoute'

const route = ref<RootRoute>(parseRootRoute(location.search))
/** 大厅「开始新建笔录」进入台账时直接打开身份录入；仅本次导航有效，不写入地址栏。 */
const startNew = ref(false)

function go(next: RootRoute) {
  startNew.value = false
  route.value = next
  history.replaceState(null, '', rootRouteUrl(location.href, next))
}

const openCase = (caseId: string) => go({ page: 'case', caseId })
const openCases = () => go({ page: 'cases' })
function startNewRecord() {
  go({ page: 'cases' })
  startNew.value = true
}
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
    <SystemSettingsView v-else-if="route.page === 'settings'" @back="openAdmin" />
    <LoginView v-else-if="route.page === 'login'" @back="openHome" @admin="openAdmin" />
    <KioskHomeView v-else-if="route.page === 'home'" @start="startNewRecord" @police-entry="openLogin" />
    <AdminShell v-else-if="route.page === 'admin'" title="管理面板" back-label="返回大厅" @back="openHome" @lock="openHome">
      <AdminPanelView
        @cases="openCases"
        @pending="go({ page: 'admin-pending' })"
        @audit="go({ page: 'admin-audit' })"
        @voiceprints="openSettings"
        @placeholder="openPlaceholder"
      />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-case'" title="案件详情" back-label="返回案件记录" @back="openCases" @lock="openHome">
      <AdminCaseDetailView :key="route.adminCaseId" :case-id="route.adminCaseId" @open="openCase" />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-pending'" title="未完成办理" @back="openAdmin" @lock="openHome">
      <AdminPendingView @open="openCase" @detail="(caseId) => go({ page: 'admin-case', adminCaseId: caseId })" />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-audit'" title="操作日志" @back="openAdmin" @lock="openHome">
      <AdminAuditView />
    </AdminShell>
    <AdminShell v-else-if="route.page !== 'cases'" :title="ADMIN_TITLES[route.page] ?? '后台管理'" @back="openAdmin" @lock="openHome">
      <EmptyState kind="pending" :title="ADMIN_TITLES[route.page] ?? '后台管理'" />
    </AdminShell>
    <AdminShell v-else title="全部案件记录" @back="openAdmin" @lock="openHome">
      <CaseDashboardView
        :auto-new="startNew"
        @open="openCase"
        @detail="(caseId) => go({ page: 'admin-case', adminCaseId: caseId })"
        @new-cancelled="openHome"
      />
    </AdminShell>
  </MaintenanceGate>
  <OnScreenKeyboard />
</template>
