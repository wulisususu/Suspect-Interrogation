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
import SelfServiceWorkspace from './views/SelfServiceWorkspace.vue'
import { fetchAuthSession } from './api/officers'
import { backendErrorMessage, createCaseWithIdentity } from './api/interrogation'
import { officerSessionActive } from './utils/officerAuth'
import { parseRootRoute, rootRouteUrl, type AdminPanel, type LoginTarget, type RootRoute } from './utils/rootRoute'

const route = ref<RootRoute>(parseRootRoute(location.search))
/** 大厅入口新建案件时，是否正在建案（防止连点建出多个空案）。 */
const creatingCase = ref(false)
const lobbyError = ref('')
/** 手动锁屏：锁定期间业务页面整体卸载，只留锁屏遮罩。 */
const locked = ref(false)

function go(next: RootRoute) {
  freshCaseId.value = ''
  route.value = next
  history.replaceState(null, '', rootRouteUrl(location.href, next))
}

/** 新建的案件按样板流程从①选模板开始（读卡建案 → 选模板 → 建档 → 问答），仅本次进入有效。 */
const freshCaseId = ref('')
/** 本次新建的案件走哪种模式：自助模式建档后交当事人本人作答。 */
const newCaseSelfService = ref(false)
const openCase = (caseId: string) => go({ page: 'case', caseId })
function openNewCase(caseId: string) {
  const selfService = newCaseSelfService.value
  go({ page: 'case', caseId, ...(selfService ? { selfService } : {}) })
  freshCaseId.value = caseId
}
const openCases = () => go({ page: 'cases' })

/**
 * 从大厅直接开始一次新询问。
 *
 * 以前这里先进台账再弹"新建询问"浮窗读身份证；现在身份信息在 ② 建档页录入，
 * 所以直接建一个待录入的空案并落到 ① 选模板，少一次打断、也少一次读卡依赖。
 */
async function startNewRecord(selfService = false) {
  if (creatingCase.value) return
  creatingCase.value = true
  lobbyError.value = ''
  newCaseSelfService.value = selfService
  try {
    const session = await fetchAuthSession()
    const officer = session.officer
    const item = await createCaseWithIdentity({
      operatorId: officer?.badgeNumber ?? '',
      officerName: officer?.name ?? '',
      caseType: 'suspect_interrogation',
      identity: { name: '待录入', source: 'MANUAL' },
    })
    openNewCase(item.id)
  } catch (error) {
    lobbyError.value = backendErrorMessage(error)
  } finally {
    creatingCase.value = false
  }
}
const openLogin = () => go({ page: 'login' })

/** 大厅入口：人工模式、自助模式与管理面板都要民警先验证身份，登录当天有效。
 *
 * 当天第一次点击时在首页弹出验证框；验证成功后留在首页，等民警再点一次才进入对应页面，
 * 避免"点了人工模式却被直接带进建档"这种替民警做决定的行为。
 */
const loginOpen = ref(false)
const loginTarget = ref<LoginTarget>('admin')

async function enter(target: LoginTarget) {
  if (await officerSessionActive()) {
    afterLogin(target)
    return
  }
  loginTarget.value = target
  loginOpen.value = true
}

/** 弹窗里验证通过：只关掉弹窗，页面停在首页，并提示民警再点一次进入。 */
const loginHint = ref('')
let loginHintTimer = 0
const TARGET_LABELS: Record<LoginTarget, string> = { manual: '人工模式', self: '自助模式', admin: '管理面板' }

function finishDialogLogin() {
  loginOpen.value = false
  loginHint.value = `身份已验证 · 请再次点击「${TARGET_LABELS[loginTarget.value]}」进入`
  window.clearTimeout(loginHintTimer)
  loginHintTimer = window.setTimeout(() => { loginHint.value = '' }, 5000)
}
async function afterLogin(target: LoginTarget = 'admin') {
  if (target === 'admin') {
    openAdmin()
    return
  }
  await startNewRecord(target === 'self')
}
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
    <SelfServiceWorkspace
      v-if="route.page === 'case' && route.selfService"
      :key="`self-${route.caseId}`"
      :case-id="route.caseId"
      :start-at-template="freshCaseId === route.caseId"
      @handover="openCase(route.caseId)"
      @exit="openHome"
    />
    <InterrogationWorkspace v-else-if="route.page === 'case'" :key="route.caseId" :case-id="route.caseId" :start-at-template="freshCaseId === route.caseId" @back="openCases" />
    <LoginView v-else-if="route.page === 'login'" :next="route.next" @back="openHome" @authenticated="afterLogin(route.next)" />
    <KioskHomeView v-else-if="route.page === 'home'" @enter="enter" />
    <AdminShell v-else-if="route.page === 'admin'" title="管理面板" back-label="返回大厅" @back="openHome" @lock="lock">
      <AdminPanelView
        @cases="openCases"
        @pending="go({ page: 'admin-pending' })"
        @audit="go({ page: 'admin-audit' })"
        @placeholder="openPlaceholder"
      />
    </AdminShell>
    <AdminShell v-else-if="route.page === 'admin-case'" title="案件详情" back-label="返回案件记录" @back="openCases" @lock="lock">
      <AdminCaseDetailView
        :key="route.adminCaseId"
        :case-id="route.adminCaseId"
        @open="openCase"
        @recordings="(caseId) => go({ page: 'admin-placeholder', panel: 'recordings', recordingCaseId: caseId })"
      />
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
      <RecordingAdminView v-else-if="route.panel === 'recordings'" :case-id="route.recordingCaseId" @login="openLogin" />
      <AdminPlaceholderView v-else :key="route.panel" :kind="route.panel" @open="openPlaceholder" />
    </AdminShell>
    <AdminShell v-else title="全部案件记录" @back="openAdmin" @lock="lock">
      <CaseDashboardView
        :auto-new="false"
        @open="openCase"
        @created="openNewCase"
        @detail="(caseId) => go({ page: 'admin-case', adminCaseId: caseId })"
        @new-cancelled="openHome"
      />
    </AdminShell>
    <p v-if="loginHint" class="login-success-toast" role="status">{{ loginHint }}</p>
    <p v-if="lobbyError" class="lobby-error-toast" role="alert">{{ lobbyError }}</p>
    <!-- 首页验证弹窗：与路由链并列，登录成功后停留原页 -->
    <LoginView
      v-if="loginOpen"
      dialog
      :next="loginTarget"
      @back="loginOpen = false"
      @authenticated="finishDialogLogin"
    />
  </MaintenanceGate>
  <OnScreenKeyboard />
</template>

<style scoped>
.lobby-error-toast { position: fixed; left: 50%; bottom: 36px; transform: translateX(-50%); z-index: 62; margin: 0; padding: 12px 20px; border-radius: 12px; background: var(--danger-700, #b91c1c); color: #fff; font-size: 14px; max-width: min(640px, 90vw); }
.login-success-toast { position: fixed; left: 50%; bottom: 36px; transform: translateX(-50%); z-index: 61; margin: 0; padding: 12px 20px; border-radius: 999px; background: var(--success-700, #15803d); color: #fff; font-size: 14px; box-shadow: 0 8px 24px rgba(0,0,0,.18); }
</style>
