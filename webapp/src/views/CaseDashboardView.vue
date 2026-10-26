<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Archive, CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, FilePenLine, FileText, Mic, RefreshCw, Search, SearchX, ShieldCheck } from '@lucide/vue'
import { backendErrorMessage, fetchCases, fetchRuntimeCapabilities } from '../api/interrogation'
import { fetchOfficerVoiceProfiles } from '../api/officerVoiceprints'
import FilterSelect, { type FilterOption } from '../components/FilterSelect.vue'
import IdentityIntakeModal from '../components/IdentityIntakeModal.vue'
import type { RuntimeCapabilities, RuntimeCapabilityName } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'

type CasePhase = 'PREPARE' | 'IN_PROGRESS' | 'REVIEW' | 'SIGNING' | 'DONE'
const emit = defineEmits<{ open: [caseId: string]; settings: []; login: [] }>()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const error = ref('')
const searchTerm = ref('')
const activeQuery = ref('')
const identityOpen = ref(false)
// 筛选统一为下拉框：状态 / 类型 / 民警 + 更新时间区间，改完即时生效
const statusFilter = ref('')
const officerFilter = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const selectedTypes = ref<string[]>([])
const page = ref(1)
const pageSize = 6
const devices = ref<RuntimeCapabilities | null>(null)
const deviceError = ref('')
const voiceprintCount = ref<number | null>(null)
const voiceprintSeconds = ref<number | null>(null)
let requestGeneration = 0

function phase(item: CaseSummary): CasePhase {
  const workflow = item.workflowState || ''
  if (workflow === 'REPORT_GENERATED' || item.state === 'ARCHIVED' || item.state === 'COMPLETED') return 'DONE'
  if (workflow === 'FROZEN' || workflow === 'SIGNED' || item.state === 'SIGNING') return 'SIGNING'
  if (workflow === 'SUMMARY' || item.state === 'REVIEWING') return 'REVIEW'
  if (workflow === 'QUESTIONING' || workflow === 'PAUSED' || item.state === 'INTERROGATING') return 'IN_PROGRESS'
  return 'PREPARE'
}
function phaseName(item: CaseSummary) {
  const value = phase(item)
  return { IN_PROGRESS: '审讯中', REVIEW: '待复核', SIGNING: item.workflowState === 'SIGNED' ? '已签名' : '待签署', DONE: '已完成', PREPARE: '待准备' }[value]
}
function phaseStep(item: CaseSummary) {
  const value = phase(item)
  return { PREPARE: 1, IN_PROGRESS: 2, REVIEW: 3, SIGNING: 4, DONE: 4 }[value]
}
function stepName(item: CaseSummary) {
  const value = phase(item)
  return { PREPARE: '准备', IN_PROGRESS: '审讯', REVIEW: '复核', SIGNING: '签署', DONE: '已完成' }[value]
}
function formatTime(timestamp?: number) {
  if (timestamp == null || !Number.isFinite(timestamp)) return '—'
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (number: number) => String(number).padStart(2, '0')
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes())
}
function isToday(timestamp?: number) {
  if (!timestamp) return false
  const a = new Date(timestamp)
  const b = new Date()
  return a.toDateString() === b.toDateString()
}
function isIdentityPrefix(value: string) {
  return /^\d{7,}$/.test(value)
}
async function load(query = '') {
  const generation = ++requestGeneration
  activeQuery.value = query
  loading.value = true
  error.value = ''
  try {
    // 保持当前 API 的查询和数量上限，不用客户端假数据充数。
    const result = await fetchCases(query ? 100 : 50, query)
    if (generation !== requestGeneration) return
    cases.value = result
    page.value = 1
  } catch (cause) {
    if (generation !== requestGeneration) return
    error.value = backendErrorMessage(cause)
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}
function handleSearchInput() {
  const value = searchTerm.value.trim()
  if (!value) { void load(); return }
  if (isIdentityPrefix(value)) { void load(value); return }
  if (activeQuery.value) void load()
}
function submitSearch() {
  const value = searchTerm.value.trim()
  if (!value) { void load(); return }
  if (/^\d+$/.test(value) && !isIdentityPrefix(value)) return
  void load(value)
}
async function refreshDevices() {
  deviceError.value = ''
  try { devices.value = await fetchRuntimeCapabilities(true) }
  catch (cause) { deviceError.value = backendErrorMessage(cause); devices.value = null }
}
async function loadVoiceprints() {
  try {
    const profiles = await fetchOfficerVoiceProfiles(true)
    voiceprintCount.value = profiles.filter((item) => item.active).length
    voiceprintSeconds.value = profiles.filter((item) => item.active).reduce((total, item) => total + Math.max(0, item.usableDurationMs), 0) / 1000
  } catch {
    voiceprintCount.value = null
    voiceprintSeconds.value = null
  }
}
async function created(item: CaseSummary) {
  identityOpen.value = false
  cases.value = [item, ...cases.value.filter((row) => row.id !== item.id)]
  emit('open', item.id)
}
function resetFilters() {
  statusFilter.value = ''
  officerFilter.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  selectedTypes.value = []
  page.value = 1
}
function clearSearch() {
  searchTerm.value = ''
  resetFilters()
  void load()
}
function caseTypeLabel(value?: string) { return value === 'suspect_interrogation' ? '嫌疑人询问' : value || '未填写' }
function capabilityText(key: RuntimeCapabilityName) {
  if (!devices.value) return '未获取'
  const entry = devices.value[key]
  if (!entry) return '未获取'
  if (entry.state === 'AVAILABLE') return '正常'
  if (entry.state === 'BUSY') return '忙碌'
  return '不可用'
}
function capabilityHealthy(key: RuntimeCapabilityName) { return devices.value?.[key]?.state === 'AVAILABLE' }
function asDate(timestamp?: number) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0')
}
const counters = computed(() => ({
  IN_PROGRESS: cases.value.filter((item) => phase(item) === 'IN_PROGRESS').length,
  REVIEW: cases.value.filter((item) => phase(item) === 'REVIEW').length,
  SIGNING: cases.value.filter((item) => phase(item) === 'SIGNING').length,
  DONE: cases.value.filter((item) => phase(item) === 'DONE').length,
  PREPARE: cases.value.filter((item) => phase(item) === 'PREPARE').length,
}))
const todayCount = computed(() => cases.value.filter((item) => isToday(item.createdAt)).length)
const officers = computed(() => [...new Set(cases.value.map((item) => item.officerName).filter(Boolean))].sort())
const caseTypes = computed(() => [...new Set(cases.value.map((item) => item.caseType).filter((value): value is string => Boolean(value)))].sort())
const appliedFilterCount = computed(() => Number(Boolean(statusFilter.value)) + selectedTypes.value.length + Number(Boolean(officerFilter.value)) + Number(Boolean(dateFrom.value || dateTo.value)))

// 下拉选项：状态带计数，类型与民警按现有数据去重
const statusFilterOptions = computed<FilterOption[]>(() => [
  { key: 'PREPARE', label: '待准备', count: counters.value.PREPARE },
  { key: 'IN_PROGRESS', label: '审讯中', count: counters.value.IN_PROGRESS },
  { key: 'REVIEW', label: '待复核', count: counters.value.REVIEW },
  { key: 'SIGNING', label: '待签署', count: counters.value.SIGNING },
  { key: 'DONE', label: '已完成', count: counters.value.DONE },
])
const typeFilterOptions = computed<FilterOption[]>(() => caseTypes.value.map((type) => ({ key: type, label: caseTypeLabel(type) })))
const officerFilterOptions = computed<FilterOption[]>(() => officers.value.map((name) => ({ key: name, label: name })))
const filteredCases = computed(() => cases.value.filter((item) => {
  if (statusFilter.value && phase(item) !== statusFilter.value) return false
  if (selectedTypes.value.length && !selectedTypes.value.includes(item.caseType || '')) return false
  if (officerFilter.value && item.officerName !== officerFilter.value) return false
  const day = asDate(item.updatedAt)
  if (dateFrom.value && (!day || day < dateFrom.value)) return false
  if (dateTo.value && (!day || day > dateTo.value)) return false
  return true
}))
const pages = computed(() => Math.max(1, Math.ceil(filteredCases.value.length / pageSize)))
const visibleCases = computed(() => filteredCases.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([statusFilter, officerFilter, dateFrom, dateTo], () => { page.value = 1 })
const voiceprintDuration = computed(() => {
  if (voiceprintSeconds.value === null) return '暂无法获取'
  const seconds = Math.floor(voiceprintSeconds.value)
  return Math.floor(seconds / 60) + ' 分 ' + seconds % 60 + ' 秒'
})
onMounted(() => { void load(); void refreshDevices(); void loadVoiceprints() })
</script>

<template>
  <main class="case-dashboard case-list-page" :class="{ 'search-empty-state': !loading && !error && !filteredCases.length && (activeQuery || cases.length) }">
    <div class="dashboard-columns">
      <section class="case-primary">
        <header class="dashboard-title-row">
          <div>
            <h1>案件管理</h1>
            <p>今日新增 {{ todayCount }} 起 · 进行中 {{ counters.IN_PROGRESS }} 起 · 待复核 {{ counters.REVIEW }} 起</p>
          </div>
          <div class="dashboard-actions">
            <button type="button" class="case-action-primary" @click="identityOpen = true">＋ 新建询问</button>
          </div>
        </header>

        <section class="dashboard-statistics" aria-label="当前已载入案件统计">
          <div class="stat-box stat-red"><span class="stat-icon"><Mic :size="26" /></span><div><strong>{{ counters.IN_PROGRESS }}</strong><small>进行中的审讯</small></div></div>
          <div class="stat-box stat-amber"><span class="stat-icon"><FileText :size="26" /></span><div><strong>{{ counters.REVIEW }}</strong><small>待复核笔录</small></div></div>
          <div class="stat-box stat-blue"><span class="stat-icon"><FilePenLine :size="26" /></span><div><strong>{{ counters.SIGNING }}</strong><small>待签署案件</small></div></div>
          <div class="stat-box stat-green"><span class="stat-icon"><Archive :size="26" /></span><div><strong>{{ counters.DONE }}</strong><small>报告已生成</small></div></div>
        </section>

        <section class="dashboard-toolbar" aria-label="案件检索">
          <form class="dashboard-search" @submit.prevent="submitSearch">
            <Search :size="17" aria-hidden="true" />
            <input v-model="searchTerm" aria-label="按姓名或身份证搜索" placeholder="姓名或身份证前 7 位" @input="handleSearchInput" />
            <button type="submit" class="search-submit" :disabled="loading || !searchTerm.trim()">查询</button>
          </form>
          <div class="dashboard-filters" aria-label="案件筛选">
            <FilterSelect v-model="statusFilter" label="状态" :options="statusFilterOptions" all-label="全部状态" />
            <FilterSelect v-model="selectedTypes" label="类型" :options="typeFilterOptions" multiple all-label="全部类型" />
            <FilterSelect v-model="officerFilter" label="民警" :options="officerFilterOptions" all-label="全部民警" />
            <label class="filter-range">
              <span class="filter-range-label">更新</span>
              <input v-model="dateFrom" type="date" aria-label="更新开始日期" />
              <em>至</em>
              <input v-model="dateTo" type="date" aria-label="更新结束日期" :min="dateFrom || undefined" />
            </label>
            <button v-if="appliedFilterCount" type="button" class="filter-reset" @click="resetFilters">重置 · {{ appliedFilterCount }}</button>
          </div>
        </section>

        <section class="case-table-shell">
          <p v-if="loading" class="dashboard-info" role="status">正在读取案件记录…</p>
          <p v-else-if="error" class="dashboard-info dashboard-error" role="alert">{{ error }} <button @click="load(activeQuery)">重试</button></p>
          <template v-else>
            <div class="case-table-scroll">
              <table v-if="filteredCases.length" class="case-dashboard-table">
                <thead><tr><th>案件编号</th><th>嫌疑人</th><th>案件类型</th><th>主审民警</th><th>阶段进度</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
                <tbody>
                  <tr v-for="item in visibleCases" :key="item.id" :class="{ 'active-case-row': phase(item) === 'IN_PROGRESS' }">
                    <td class="id-column">{{ item.id }}</td>
                    <td><strong>{{ item.suspectName || '待录入' }}</strong><small>{{ item.gender || '—' }} · {{ item.age || '年龄未录入' }} · {{ item.identitySource ? '身份信息已录入' : '身份待核对' }}</small></td>
                    <td>{{ item.caseType === 'suspect_interrogation' ? '嫌疑人询问' : item.caseType || '—' }}</td>
                    <td>{{ item.officerName || '—' }}</td>
                    <td class="phase-cell">
                      <div class="stage-bars" :aria-label="stepName(item) + '，第 ' + phaseStep(item) + ' / 4 阶段'">
                        <i v-for="step in 4" :key="step" :class="{ filled: step <= phaseStep(item), current: step === phaseStep(item) && phase(item) !== 'DONE' }"></i>
                      </div>
                      <span>{{ stepName(item) }} · {{ phaseStep(item) }}/4</span>
                    </td>
                    <td><span class="phase-tag" :data-phase="phase(item)">{{ phaseName(item) }}</span></td>
                    <td>{{ formatTime(item.updatedAt) }}</td>
                    <td><button class="enter-case" @click="emit('open', item.id)">{{ phase(item) === 'DONE' ? '查看' : '进入' }} →</button></td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!filteredCases.length" class="dashboard-empty">
                <SearchX v-if="activeQuery || cases.length" :size="64" :stroke-width="1.5" /><ClipboardList v-else :size="64" :stroke-width="1.5" />
                <h2>{{ activeQuery || cases.length ? '未找到匹配的案件' : '暂无案件记录' }}</h2>
                <p>{{ activeQuery ? '关键词「' + activeQuery + '」暂无匹配结果。' : cases.length ? '当前筛选条件下暂无匹配结果。' : '创建第一起询问，开始登记身份并准备笔录。' }}</p>
                <ul v-if="activeQuery || cases.length" class="empty-suggestions"><li>核对完整姓名，或使用身份证前 7 位重新检索</li><li>尝试清空案件状态、民警和时间范围等筛选条件</li><li>被询问人可能尚未建档，可直接新建询问</li></ul>
                <div class="empty-actions"><button v-if="activeQuery || cases.length" @click="clearSearch">清空搜索条件</button><button class="case-action-primary" @click="identityOpen = true">新建询问</button></div>
              </div>
            </div>
            <footer v-if="filteredCases.length" class="case-table-footer">
              <span>已载入 {{ cases.length }} 起案件，当前筛选 {{ filteredCases.length }} 起{{ cases.length >= (activeQuery ? 100 : 50) ? '（列表可能存在更多历史记录）' : '' }}</span>
              <div class="page-controls">
                <button :disabled="page <= 1" @click="page -= 1"><ChevronLeft :size="15" /> 上一页</button>
                <span>第 {{ page }} / {{ pages }} 页</span>
                <button class="next-page" :disabled="page >= pages" @click="page += 1">下一页 <ChevronRight :size="15" /></button>
              </div>
            </footer>
          </template>
        </section>
      </section>

      <aside class="dashboard-sidebar" aria-label="辅助状态">
        <section class="sidebar-card voice-card">
          <div class="sidebar-card-head"><h2>民警声纹库</h2><span class="green-pill">{{ voiceprintCount === null ? '待确认' : '已载入' }}</span></div>
          <p>有效档案 {{ voiceprintCount === null ? '—' : voiceprintCount }} 条 · 有效语音 {{ voiceprintDuration }}</p>
          <p class="muted">登记后新建询问时可直接选用，跨案件复用。</p>
          <button class="text-link" @click="emit('settings')">管理声纹库 →</button>
        </section>

        <section class="sidebar-card readiness-card">
          <h2>开始前自检</h2>
          <p class="muted">三项就绪后即可开始新询问</p>
          <div v-for="cap in [
            { key: 'identity', title: '身份证读卡器' },
            { key: 'microphone', title: '一体机麦克风' },
            { key: 'asr', title: '语音识别服务' }
          ]" :key="cap.key" class="device-status">
            <span class="device-dot" :class="{ good: capabilityHealthy(cap.key as RuntimeCapabilityName) }"></span>
            <span>{{ cap.title }} · {{ capabilityText(cap.key as RuntimeCapabilityName) }}</span>
          </div>
          <p v-if="deviceError" class="device-error">设备状态暂不可获取，请检查后端连接。</p>
          <button class="device-refresh" @click="refreshDevices"><RefreshCw :size="15" /> 重新自检</button>
        </section>

        <section class="sidebar-card workflow-card">
          <h2>询问流程</h2>
          <div class="workflow-step"><ShieldCheck :size="15" /><span>准备 · 核对身份与声纹注册</span></div>
          <div class="workflow-step"><Mic :size="15" /><span>审讯 · 实时转写与说话人识别</span></div>
          <div class="workflow-step"><FileText :size="15" /><span>复核 · 片段核对录入笔录</span></div>
          <div class="workflow-step"><CheckCircle2 :size="15" /><span>签署 · 冻结后打印、手写签名</span></div>
        </section>
      </aside>
    </div>
    <IdentityIntakeModal v-if="identityOpen" @close="identityOpen = false" @created="created" />
  </main>
</template>

<style scoped>
.case-dashboard { --navy: var(--primary-700); --blue: var(--primary-600); display: flex; flex-direction: column; height: calc(100vh - 54px); overflow: auto; background: var(--surface-sunken); color: var(--navy-900); padding: 28px 32px 40px; font-size: var(--text-md); }
.dashboard-columns { display: grid; flex: 1 1 auto; min-height: 0; grid-template-columns: minmax(0, 1fr) 266px; gap: 26px; max-width: 1800px; margin: 0 auto; align-items: stretch; width: 100%; }
.case-primary { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.dashboard-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin: 4px 0 15px; }
.dashboard-title-row h1 { font-size: var(--text-2xl); line-height: 1.25; margin: 0 0 7px; }
.dashboard-title-row p { margin: 0; color: var(--ink-500); }
.dashboard-actions { display: flex; gap: 10px; }
.case-action-primary { background: var(--primary-600); border: 1px solid var(--primary-600); color: white; padding: 12px 18px; border-radius: 8px; font-size: var(--text-md); font-weight: 700; white-space: nowrap; }
.case-action-primary:hover { background: var(--primary-700); }
.dashboard-statistics { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 12px; margin: 16px 0 18px; }
.stat-box { display: flex; align-items: center; gap: 12px; height: 96px; padding: 17px; background: var(--surface); border: 1px solid var(--primary-100); border-radius: 12px; }
.stat-icon { width: 44px; height: 44px; display: grid; place-items: center; flex-shrink: 0; border-radius: 10px; }
.stat-box strong { display: block; font-size: var(--text-2xl); line-height: 1.15; font-weight: 760; }
.stat-box small { display: block; margin-top: 4px; color: var(--ink-500); font-size: var(--text-base); }
.stat-red .stat-icon { color: var(--danger-700); background: var(--danger-100); } .stat-red strong { color: var(--danger-700); }
.stat-amber .stat-icon { color: var(--warning-600); background: var(--warning-100); } .stat-amber strong { color: var(--warning-600); }
.stat-blue .stat-icon { color: var(--primary-600); background: var(--surface-sunken); } .stat-blue strong { color: var(--primary-600); }
.stat-green .stat-icon { color: var(--success-700); background: var(--success-100); } .stat-green strong { color: var(--success-700); }
.dashboard-toolbar { display: flex; align-items: center; gap: 9px; margin-bottom: 17px; flex-wrap: wrap; }
.dashboard-search { display: flex; align-items: center; gap: 8px; min-width: 210px; width: min(262px, 100%); height: 46px; background: var(--surface); border: 1px solid var(--primary-100); border-radius: 8px; padding: 0 12px; color: var(--ink-400); }
.dashboard-search input { width: 100%; min-width: 0; flex: 1; height: 100%; border: 0; outline: 0; color: var(--primary-700); background: transparent; font-size: var(--text-md); }
.dashboard-search input::placeholder { color: var(--ink-400); }
.search-submit { border: 0; background: none; padding: 6px 8px; font-size: var(--text-md); font-weight: 650; color: var(--primary-600); white-space: nowrap; }
.rotated { transform: rotate(180deg); }
.filter-footnote { flex-basis: 100%; margin: 0; color: var(--ink-400); font-size: var(--text-sm); }
.case-table-shell { display: flex; flex: 1 1 auto; flex-direction: column; min-height: 0; background: var(--surface); border-radius: 12px; overflow: hidden; }
.case-table-scroll { display: flex; flex: 1 1 auto; flex-direction: column; min-height: 0; width: 100%; overflow-x: auto; }
.case-dashboard-table { width: 100%; height: 100%; border-collapse: collapse; text-align: left; font-size: var(--text-base); }
.case-dashboard-table th { padding: 17px 12px; background: var(--surface-sunken); color: var(--ink-400); font-size: var(--text-base); font-weight: 650; white-space: nowrap; }
.case-dashboard-table td { height: 71px; padding: 11px 12px; border-bottom: 1px solid var(--primary-100); vertical-align: middle; color: var(--primary-700); white-space: nowrap; }
.case-dashboard-table tbody tr:hover { background: var(--surface-sunken); }
.case-dashboard-table tbody tr.active-case-row { box-shadow: inset 4px 0 var(--danger-700); }
.case-dashboard-table td.id-column { font-weight: 720; color: var(--primary-600); }
.case-dashboard-table td strong { display: block; margin-bottom: 3px; font-weight: 720; }
.case-dashboard-table td small { display: block; color: var(--ink-400); font-size: var(--text-sm); }
.phase-cell { min-width: 174px; }
.stage-bars { display: inline-flex; align-items: center; gap: 4px; vertical-align: middle; margin-right: 6px; }
.stage-bars i { width: 24px; height: 10px; border-radius: 3px; background: var(--primary-100); }
.stage-bars i.filled { background: var(--primary-500); }
.stage-bars i.current { background: var(--primary-600); }
.phase-cell span { color: var(--primary-600); font-size: var(--text-sm); white-space: nowrap; }
.phase-tag { display: inline-flex; align-items: center; justify-content: center; min-width: 76px; border-radius: 999px; padding: 9px 12px; background: var(--primary-100); color: var(--ink-500); font-size: var(--text-base); white-space: nowrap; }
.phase-tag::before { content: ''; width: 6px; height: 6px; border-radius: 100%; margin-right: 7px; background: currentColor; }
.phase-tag[data-phase="IN_PROGRESS"] { background: var(--danger-100); color: var(--danger-700); }
.phase-tag[data-phase="REVIEW"] { background: var(--warning-100); color: var(--warning-600); }
.phase-tag[data-phase="SIGNING"] { background: var(--primary-100); color: var(--primary-600); }
.phase-tag[data-phase="DONE"] { background: var(--success-100); color: var(--success-700); }
.enter-case { min-width: 72px; padding: 10px 14px; border-radius: 8px; border: 0; background: var(--primary-100); color: var(--primary-600); font-size: var(--text-md); font-weight: 700; white-space: nowrap; }
.enter-case:hover { background: var(--primary-600); color: var(--surface); }
.case-table-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 66px; padding: 12px 16px; color: var(--ink-400); font-size: var(--text-sm); }
.page-controls { display: flex; align-items: center; gap: 9px; }
.page-controls button { display: inline-flex; align-items: center; gap: 4px; padding: 10px 14px; border: none; border-radius: 7px; background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-md); }
.page-controls button.next-page { color: var(--surface); background: var(--primary-600); }
.page-controls button:disabled { opacity: .45; }
.dashboard-info { padding: 42px 25px; text-align: center; color: var(--ink-500); }
.dashboard-error { color: var(--danger-600); }
.dashboard-error button { color: var(--primary-600); border: none; background: none; font-size: var(--text-md); }
.dashboard-empty { display: flex; flex: 1 0 auto; flex-direction: column; align-items: center; justify-content: center; gap: 18px; padding: 48px 30px; color: var(--primary-500); text-align: center; }
.dashboard-empty h2 { font-size: var(--text-2xl); color: var(--primary-700); margin: 0; }
.dashboard-empty p { color: var(--ink-400); margin: 0; font-size: var(--text-md); }
.empty-suggestions { width: min(580px,100%); padding: 18px 30px 18px 42px; margin: 2px 0 4px; border-radius: 10px; background: var(--surface-sunken); text-align: left; color: var(--primary-600); font-size: var(--text-base); line-height: 2; }
.empty-actions { display: flex; gap: 12px; }
.dashboard-empty button { border: 1px solid var(--primary-100); color: var(--ink-500); background: var(--surface); border-radius: 8px; padding: 13px 20px; font-size: var(--text-md); }
.dashboard-empty .case-action-primary { background: var(--primary-600); color: var(--surface); border-color: var(--primary-600); }
.search-empty-state .dashboard-columns { grid-template-columns: minmax(0,1fr); }
.search-empty-state .dashboard-title-row,.search-empty-state .dashboard-statistics,.search-empty-state .dashboard-sidebar,.search-empty-state .status-tabs,.search-empty-state .filter-toggle,.search-empty-state .advanced-filters { display: none; }
.search-empty-state .case-table-shell { flex: 0 0 auto; width: min(820px,100%); min-height: 480px; margin: auto; }
.search-empty-state .dashboard-empty { padding: 48px; }
.dashboard-sidebar { display: grid; grid-template-rows: max-content max-content 1fr; min-height: 0; gap: 14px; }
.sidebar-card { padding: 20px; border: 1px solid var(--primary-100); border-radius: 12px; background: var(--surface); }
.sidebar-card-head { display: flex; align-items: center; justify-content: space-between; gap: 7px; }
.sidebar-card h2 { font-size: var(--text-lg); line-height: 1.2; margin: 0 0 15px; font-weight: 750; }
.sidebar-card-head h2 { margin-bottom: 0; }
.sidebar-card p { margin: 11px 0; color: var(--ink-500); font-size: var(--text-base); line-height: 1.6; }
.sidebar-card p.muted { color: var(--ink-400); }
.green-pill { padding: 5px 10px; background: var(--success-100); color: var(--success-700); border-radius: 20px; font-size: var(--text-xs); white-space: nowrap; }
.text-link { border: 0; background: transparent; color: var(--primary-600); font-weight: 700; padding: 4px 0; font-size: var(--text-md); }
.readiness-card h2 { margin-bottom: 9px; }
.device-status { display: flex; align-items: center; gap: 9px; margin: 16px 0; font-size: var(--text-base); }
.device-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: var(--warning-700); }
.device-dot.good { background: var(--success-600); }
.sidebar-card p.device-error { color: var(--danger-700); }
.device-refresh { width: 100%; display: flex; align-items: center; justify-content: center; gap: 7px; padding: 12px; background: var(--surface-sunken); border: none; border-radius: 8px; color: var(--primary-600); font-weight: 700; font-size: var(--text-md); }
.workflow-card { align-self: end; margin-top: 0; }
.workflow-step { display: flex; align-items: flex-start; gap: 8px; margin: 16px 0; color: var(--ink-500); line-height: 1.5; font-size: var(--text-base); }
.workflow-step svg { flex-shrink: 0; color: var(--primary-600); margin-top: 2px; }
@media (max-width: 1480px) { .case-dashboard { padding: 23px 24px; } .dashboard-columns { grid-template-columns: minmax(0,1fr) 235px; gap: 16px; } .stat-box { padding: 12px; } .stat-icon { width: 38px; height: 38px; } .stage-bars i { width: 16px; } .case-dashboard-table th,.case-dashboard-table td { padding: 12px 9px; } }
@media (max-width: 1150px) { .dashboard-columns { grid-template-columns: 1fr; } .dashboard-sidebar { grid-template-columns: repeat(3, 1fr); } .workflow-card { margin-top: 0; } .case-dashboard-table { min-width: 970px; } }
@media (max-width: 720px) { .case-dashboard { min-width: 0; padding: 16px; } .dashboard-statistics { grid-template-columns: repeat(2,minmax(0,1fr)); } .dashboard-sidebar { grid-template-columns: 1fr; } .dashboard-title-row { align-items: center; } .filter-toggle { margin-left: 0; } .dashboard-search { width: 100%; } .case-table-footer { flex-wrap: wrap; } }
@media (max-height: 720px) { .case-dashboard { height: auto; min-height: calc(100vh - 54px); } .dashboard-columns { flex: 0 0 auto; } .case-primary { min-height: 600px; } }
@media (max-width: 720px) { .advanced-filters { grid-template-columns: 1fr; padding: 18px; } .empty-actions { flex-wrap: wrap; } }

.dashboard-filters { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); flex: 1 1 auto; }
.filter-range {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 38px;
  padding: 0 var(--space-3);
  border: 1px solid var(--line-300);
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: var(--text-sm);
  color: var(--ink-400);
}
.filter-range-label { color: var(--ink-400); }
.filter-range em { color: var(--ink-300); font-style: normal; }
.filter-range input {
  width: 108px;
  min-height: 28px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--ink-700);
  font-size: var(--text-sm);
  font-family: inherit;
}
.filter-range input:focus { outline: none; box-shadow: var(--shadow-focus); background: var(--surface); }
.filter-reset {
  min-height: 38px;
  padding: 0 var(--space-3);
  border: 1px solid var(--line-300);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--primary-600);
  font-size: var(--text-sm);
}
.filter-reset:hover { border-color: var(--primary-200); background: var(--primary-50); }
</style>