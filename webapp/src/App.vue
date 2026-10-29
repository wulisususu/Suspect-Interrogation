<script setup lang="ts">
import { ref } from 'vue'
import AdminShell from './components/AdminShell.vue'
import LockScreen from './components/LockScreen.vue'
import MaintenanceGate from './components/MaintenanceGate.vue'
import OnScreenKeyboard from './components/OnScreenKeyboard.vue'
import AdminAuditView from './views/AdminAuditView.vue'
import AdminCaseDetailView from './views/AdminCaseDetailView.vue'
import AdminPendingView from './views/AdminPendingView.vue'
import AdminPlaceholderView from './views/AdminPlaceholderView.vue'
import AdminPanelView from './views/AdminPanelView.vue'
import CaseDashboardView from './views/CaseDashboardView.vue'
import KioskHomeView from './views/KioskHomeView.vue'
import LoginView from './views/LoginView.vue'
import InterrogationWorkspace from './views/InterrogationWorkspace.vue'
import KnowledgeAdminView from './views/KnowledgeAdminView.vue'
import OfficerSignatureAdminView from './views/OfficerSignatureAdminView.vue'
import RecordingAdminView from './views/RecordingAdminView.vue'
import { parseRootRoute, rootRouteUrl, type AdminPanel, type RootRoute } from './utils/rootRoute'

const route = ref<RootRoute>(parseRootRoute(location.search))
/** 大厅「开始新建笔录」进入台账时直接打开身份录入；仅本次导航有效，不写入地址栏。 */
const startNew = ref(false)
/** 手动锁屏：锁定期间业务页面整体卸载，只留锁屏遮罩。 */
const locked = ref(false)

function go(next: RootRoute) {
  startNew.value = false
  freshCaseId.value = ''
  route.value = next
  history.replaceState(null, '', rootRouteUrl(location.href, next))
}

/** 新建的案件按样板流程从①选模板开始（读卡建案 → 选模板 → 建档 → 问答），仅本次进入有效。 */
const freshCaseId = ref('')
const openCase = (caseId: string) => go({ page: 'case', caseId })
function openNewCase(caseId: string) {
  go({ page: 'case', caseId })
  freshCaseId.value = caseId
}
const openCases = () => go({ page: 'cases' })
function startNewRecord() {
  go({ page: 'cases' })
  startNew.value = true
}
const openLogin = () => go({ page: 'login' })
const openHome = () => go({ page: 'home' })
const lock = () => { locked.value = true }
function unlock() {
  locked.value = false
  openLogin()
}
const openAdmin = () => go({ page: 'admin' })
const openPlaceholder = (panel: AdminPanel) => go({ page: 'admin-placeholder', panel })

const PANEL_TITLES: Record<AdminPanel, string> = {
  knowledge: '知识库管理',
  templates: '模板管理',
  'template-edit': '模板编辑',
  signatures: '民警签名管理',
  recordings: '录音查看',
}
</script>

<template>
  <LockScreen v-if="locked" @unlock="unlock" />
  <MaintenanceGate v-else>
    <InterrogationWorkspace v-if="route.page === 'case'" :key="route.caseId" :case-id="route.caseId" :start-at-template="freshCaseId === route.caseId" @back="openCases" />
    <LoginView v-else-if="route.page === 'login'" @back="openHome" @authenticated="openAdmin" />
    <KioskHomeView v-else-if="route.page === 'home'" @start="startNewRecord" @police-entry="openLogin" />
    <AdminShell v-else-if="route.page === 'admin'" title="管理面板" back-label="返回大厅" @back="openHome" @lock="lock">
      <AdminPanelView
        @cases="openCases"
        @pending="go({ page: 'admin-pending' })"
        @audit="go({ page: 'admin-audit' })"
        @placeholder="openPlaceholder"
      />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-case'" title="案件详情" back-label="返回案件记录" @back="openCases" @lock="lock">
      <AdminCaseDetailView :key="route.adminCaseId" :case-id="route.adminCaseId" @open="openCase" />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-pending'" title="未完成办理" @back="openAdmin" @lock="lock">
      <AdminPendingView @open="openCase" @detail="(caseId) => go({ page: 'admin-case', adminCaseId: caseId })" />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-audit'" title="操作日志" @back="openAdmin" @lock="lock">
      <AdminAuditView />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-placeholder'" :title="PANEL_TITLES[route.panel]" @back="openAdmin" @lock="lock">
      <KnowledgeAdminView v-if="route.panel === 'knowledge'" />
      <OfficerSignatureAdminView v-else-if="route.panel === 'signatures'" @login="openLogin" />
      <RecordingAdminView v-else-if="route.panel === 'recordings'" @login="openLogin" />
      <AdminPlaceholderView v-else :key="route.panel" :kind="route.panel" @open="openPlaceholder" />
    </AdminShell>
    <AdminShell v-else title="全部案件记录" @back="openAdmin" @lock="lock">
      <CaseDashboardView
        :auto-new="startNew"
        @open="openCase"
        @created="openNewCase"
        @detail="(caseId) => go({ page: 'admin-case', adminCaseId: caseId })"
        @new-cancelled="openHome"
      />
    </AdminShell>
  </MaintenanceGate>
  <OnScreenKeyboard />
</template>
