<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Archive, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ClipboardList, FilePenLine, FileText, Mic, RefreshCw, Search, ShieldCheck } from '@lucide/vue'
import { backendErrorMessage, fetchCases, fetchRuntimeCapabilities } from '../api/interrogation'
import { fetchOfficerVoiceProfiles } from '../api/officerVoiceprints'
import IdentityIntakeModal from '../components/IdentityIntakeModal.vue'
import type { RuntimeCapabilities, RuntimeCapabilityName } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'

type FilterStatus = 'ALL' | 'IN_PROGRESS' | 'REVIEW' | 'SIGNING' | 'DONE' | 'PREPARE'
type CasePhase = Exclude<FilterStatus, 'ALL'>
const emit = defineEmits<{ open: [caseId: string]; settings: []; login: [] }>()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const error = ref('')
const searchTerm = ref('')
const activeQuery = ref('')
const identityOpen = ref(false)
const filterExpanded = ref(false)
const statusFilter = ref<FilterStatus>('ALL')
const officerFilter = ref('')
const dateFrom = ref('')
const dateTo = ref('')
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
  statusFilter.value = 'ALL'
  officerFilter.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  page.value = 1
}
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
const filteredCases = computed(() => cases.value.filter((item) => {
  if (statusFilter.value !== 'ALL' && phase(item) !== statusFilter.value) return false
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
  <main class="case-dashboard">
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
            <input v-model="searchTerm" aria-label="按姓名或身份证搜索" placeholder="输入完整姓名，或身份证前 7 位" @input="handleSearchInput" />
            <button type="submit" class="search-submit" :disabled="loading || !searchTerm.trim()">查询</button>
          </form>
          <div class="status-tabs">
            <button v-for="option in [
              { key: 'ALL', title: '全部' },
              { key: 'IN_PROGRESS', title: '进行中' },
              { key: 'REVIEW', title: '待复核' },
              { key: 'SIGNING', title: '待签署' },
              { key: 'DONE', title: '已完成' }
            ]" :key="option.key" type="button" :class="{ selected: statusFilter === option.key }" @click="statusFilter = option.key as FilterStatus">
              {{ option.title }} {{ option.key === 'ALL' ? cases.length : counters[option.key as CasePhase] }}
            </button>
          </div>
          <button class="filter-toggle" :aria-expanded="filterExpanded" @click="filterExpanded = !filterExpanded">
            案件筛选 <ChevronDown :size="15" :class="{ rotated: filterExpanded }" />
          </button>
        </section>

        <section v-if="filterExpanded" class="advanced-filters" aria-label="高级案件筛选">
          <div class="filter-group">
            <label for="dashboard-officer">主审民警</label>
            <select id="dashboard-officer" v-model="officerFilter"><option value="">全部民警</option><option v-for="name in officers" :key="name" :value="name">{{ name }}</option></select>
          </div>
          <div class="filter-group">
            <label for="dashboard-from">更新开始日期</label>
            <input id="dashboard-from" v-model="dateFrom" type="date" />
          </div>
          <div class="filter-group">
            <label for="dashboard-to">更新结束日期</label>
            <input id="dashboard-to" v-model="dateTo" type="date" :min="dateFrom || undefined" />
          </div>
          <div class="filter-buttons">
            <button @click="resetFilters">重置筛选</button>
            <button class="case-action-primary" @click="filterExpanded = false">应用筛选 · {{ filteredCases.length }} 条</button>
          </div>
          <p class="filter-footnote">当前案件接口尚未提供具体案由和完整分页总量，故不显示虚构的案件类型选项或总数。</p>
        </section>

        <section class="case-table-shell">
          <p v-if="loading" class="dashboard-info" role="status">正在读取案件记录…</p>
          <p v-else-if="error" class="dashboard-info dashboard-error" role="alert">{{ error }} <button @click="load(activeQuery)">重试</button></p>
          <template v-else>
            <div class="case-table-scroll">
              <table class="case-dashboard-table">
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
                <ClipboardList :size="44" />
                <h2>{{ cases.length ? '没有符合条件的案件' : '暂无案件记录' }}</h2>
                <p>{{ cases.length ? '请调整检索内容或筛选条件。' : '创建第一起询问，开始登记身份并准备笔录。' }}</p>
                <button v-if="!cases.length" class="case-action-primary" @click="identityOpen = true">＋ 新建询问</button>
                <button v-else @click="resetFilters">清除筛选</button>
              </div>
            </div>
            <footer class="case-table-footer">
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
.case-dashboard { --navy: #19345e; --blue: #205293; height: calc(100vh - 54px); overflow: auto; background: #f4f6fb; color: #172640; padding: 28px 32px 40px; font-size: 13px; }
.dashboard-columns { display: grid; grid-template-columns: minmax(0, 1fr) 266px; gap: 26px; max-width: 1800px; margin: 0 auto; align-items: start; }
.case-primary { min-width: 0; }
.dashboard-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin: 4px 0 15px; }
.dashboard-title-row h1 { font-size: 23px; line-height: 1.25; margin: 0 0 7px; }
.dashboard-title-row p { margin: 0; color: #62748c; }
.dashboard-actions { display: flex; gap: 10px; }
.case-action-primary { background: #205293; border: 1px solid #205293; color: white; padding: 11px 16px; border-radius: 8px; font-weight: 700; white-space: nowrap; }
.case-action-primary:hover { background: #153c71; }
.dashboard-statistics { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 12px; margin: 16px 0 18px; }
.stat-box { display: flex; align-items: center; gap: 12px; height: 96px; padding: 17px; background: #fff; border: 1px solid #edf1f7; border-radius: 12px; }
.stat-icon { width: 44px; height: 44px; display: grid; place-items: center; flex-shrink: 0; border-radius: 10px; }
.stat-box strong { display: block; font-size: 25px; line-height: 1.15; font-weight: 760; }
.stat-box small { display: block; margin-top: 4px; color: #576980; font-size: 12px; }
.stat-red .stat-icon { color: #db352b; background: #fff0ed; } .stat-red strong { color: #da3028; }
.stat-amber .stat-icon { color: #bf790b; background: #fff4e5; } .stat-amber strong { color: #b86e00; }
.stat-blue .stat-icon { color: #205293; background: #eaf2ff; } .stat-blue strong { color: #205293; }
.stat-green .stat-icon { color: #16763e; background: #e9f8ee; } .stat-green strong { color: #16763e; }
.dashboard-toolbar { display: flex; align-items: center; gap: 9px; margin-bottom: 17px; flex-wrap: wrap; }
.dashboard-search { display: flex; align-items: center; gap: 8px; min-width: 270px; width: min(330px, 100%); height: 42px; background: #fff; border: 1px solid #dce5f1; border-radius: 8px; padding: 0 12px; color: #99a7b9; }
.dashboard-search input { width: 100%; min-width: 0; flex: 1; height: 100%; border: 0; outline: 0; color: #213955; background: transparent; font-size: 12px; }
.dashboard-search input::placeholder { color: #93a2b5; }
.search-submit { border: 0; background: none; font-size: 12px; font-weight: 650; color: #205293; white-space: nowrap; }
.status-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.status-tabs button { padding: 10px 10px; border-radius: 8px; border: 1px solid #dce5f1; background: #fff; color: #50617b; font-size: 12px; white-space: nowrap; }
.status-tabs button.selected { background: #205293; border-color: #205293; color: #fff; }
.filter-toggle { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; padding: 10px; background: #fff; border: 1px solid #dce5f1; border-radius: 8px; color: #40546e; font-size: 12px; white-space: nowrap; }
.rotated { transform: rotate(180deg); }
.advanced-filters { display: flex; align-items: end; flex-wrap: wrap; gap: 13px; margin: -2px 0 17px; padding: 18px 20px; border-radius: 12px; background: #fff; border: 1px solid #ebf0f6; }
.filter-group { min-width: 172px; display: grid; gap: 7px; flex: 1; }
.filter-group label { font-size: 12px; color: #586981; }
.filter-group input, .filter-group select { min-height: 38px; width: 100%; padding: 8px; background: #f4f6f9; border: 0; border-radius: 7px; color: #344860; }
.filter-buttons { display: flex; gap: 7px; }
.filter-buttons button:not(.case-action-primary) { padding: 9px 14px; background: #eff2f7; border: none; border-radius: 8px; color: #50617a; }
.filter-footnote { flex-basis: 100%; margin: 0; color: #8797aa; font-size: 11px; }
.case-table-shell { background: #fff; border-radius: 12px; overflow: hidden; }
.case-table-scroll { width: 100%; overflow-x: auto; }
.case-dashboard-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; }
.case-dashboard-table th { padding: 17px 12px; background: #f0f4f9; color: #77879b; font-size: 11px; font-weight: 650; white-space: nowrap; }
.case-dashboard-table td { height: 71px; padding: 11px 12px; border-bottom: 1px solid #edf0f5; vertical-align: middle; color: #243550; white-space: nowrap; }
.case-dashboard-table tbody tr:hover { background: #fbfcff; }
.case-dashboard-table tbody tr.active-case-row { box-shadow: inset 4px 0 #dd4133; }
.case-dashboard-table td.id-column { font-weight: 720; color: #245594; }
.case-dashboard-table td strong { display: block; margin-bottom: 3px; font-weight: 720; }
.case-dashboard-table td small { display: block; color: #91a0b7; font-size: 10px; }
.phase-cell { min-width: 174px; }
.stage-bars { display: inline-flex; align-items: center; gap: 4px; vertical-align: middle; margin-right: 6px; }
.stage-bars i { width: 24px; height: 10px; border-radius: 3px; background: #e4eaf3; }
.stage-bars i.filled { background: #b5cae6; }
.stage-bars i.current { background: #205293; }
.phase-cell span { color: #456588; font-size: 11px; white-space: nowrap; }
.phase-tag { display: inline-flex; align-items: center; justify-content: center; min-width: 76px; border-radius: 999px; padding: 8px 11px; background: #edf1f6; color: #66738a; font-size: 11px; white-space: nowrap; }
.phase-tag::before { content: ''; width: 6px; height: 6px; border-radius: 100%; margin-right: 7px; background: currentColor; }
.phase-tag[data-phase="IN_PROGRESS"] { background: #fff0ed; color: #c43c2c; }
.phase-tag[data-phase="REVIEW"] { background: #fff3e2; color: #b7770b; }
.phase-tag[data-phase="SIGNING"] { background: #eaf2fc; color: #245a99; }
.phase-tag[data-phase="DONE"] { background: #e7f7ec; color: #238149; }
.enter-case { min-width: 72px; padding: 9px 12px; border-radius: 8px; border: 0; background: #eaf2fc; color: #205293; font-weight: 700; white-space: nowrap; }
.enter-case:hover { background: #205293; color: #fff; }
.case-table-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 62px; padding: 12px 16px; color: #8c9ab0; font-size: 11px; }
.page-controls { display: flex; align-items: center; gap: 9px; }
.page-controls button { display: inline-flex; align-items: center; gap: 4px; padding: 9px 12px; border: none; border-radius: 7px; background: #f2f5f9; color: #60718c; }
.page-controls button.next-page { color: #fff; background: #205293; }
.page-controls button:disabled { opacity: .45; }
.dashboard-info { padding: 42px 25px; text-align: center; color: #687a91; }
.dashboard-error { color: #ae362c; }
.dashboard-error button { color: #205293; border: none; background: none; }
.dashboard-empty { display: grid; justify-items: center; gap: 11px; padding: 67px 25px; color: #b7c3d6; text-align: center; }
.dashboard-empty h2 { font-size: 18px; color: #4b5e79; margin: 0; }
.dashboard-empty p { color: #8090a5; margin: 0 0 6px; }
.dashboard-empty button { border-radius: 7px; padding: 9px 20px; }
.dashboard-sidebar { display: grid; gap: 14px; }
.sidebar-card { padding: 20px; border: 1px solid #edf1f7; border-radius: 12px; background: #fff; }
.sidebar-card-head { display: flex; align-items: center; justify-content: space-between; gap: 7px; }
.sidebar-card h2 { font-size: 14px; line-height: 1.2; margin: 0 0 15px; font-weight: 750; }
.sidebar-card-head h2 { margin-bottom: 0; }
.sidebar-card p { margin: 11px 0; color: #687993; font-size: 12px; line-height: 1.6; }
.sidebar-card p.muted { color: #96a2b4; }
.green-pill { padding: 5px 10px; background: #eaf7ee; color: #247b49; border-radius: 20px; font-size: 10px; white-space: nowrap; }
.text-link { border: 0; background: transparent; color: #245a98; font-weight: 700; padding: 0; font-size: 12px; }
.readiness-card h2 { margin-bottom: 9px; }
.device-status { display: flex; align-items: center; gap: 9px; margin: 16px 0; font-size: 12px; }
.device-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: #dd9752; }
.device-dot.good { background: #43b37b; }
.sidebar-card p.device-error { color: #b84a40; }
.device-refresh { width: 100%; display: flex; align-items: center; justify-content: center; gap: 7px; padding: 10px; background: #f1f4f9; border: none; border-radius: 8px; color: #25548a; font-weight: 700; font-size: 12px; }
.workflow-card { margin-top: 32px; }
.workflow-step { display: flex; align-items: flex-start; gap: 8px; margin: 16px 0; color: #64748b; line-height: 1.5; font-size: 12px; }
.workflow-step svg { flex-shrink: 0; color: #225b9c; margin-top: 2px; }
@media (max-width: 1480px) { .case-dashboard { padding: 23px 24px; } .dashboard-columns { grid-template-columns: minmax(0,1fr) 235px; gap: 16px; } .stat-box { padding: 12px; } .stat-icon { width: 38px; height: 38px; } .stage-bars i { width: 16px; } .case-dashboard-table th,.case-dashboard-table td { padding: 12px 9px; } }
@media (max-width: 1150px) { .dashboard-columns { grid-template-columns: 1fr; } .dashboard-sidebar { grid-template-columns: repeat(3, 1fr); } .workflow-card { margin-top: 0; } .case-dashboard-table { min-width: 970px; } }
@media (max-width: 720px) { .case-dashboard { min-width: 0; padding: 16px; } .dashboard-statistics { grid-template-columns: repeat(2,minmax(0,1fr)); } .dashboard-sidebar { grid-template-columns: 1fr; } .dashboard-title-row { align-items: center; } .filter-toggle { margin-left: 0; } .dashboard-search { width: 100%; } .case-table-footer { flex-wrap: wrap; } }
</style>
