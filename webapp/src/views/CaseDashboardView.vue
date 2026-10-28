<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Search } from '@lucide/vue'
import { backendErrorMessage, fetchCases } from '../api/interrogation'
import EmptyState from '../components/EmptyState.vue'
import FilterSelect, { type FilterOption } from '../components/FilterSelect.vue'
import IdentityIntakeModal from '../components/IdentityIntakeModal.vue'
import type { CaseSummary } from '../types/interrogation'
import { casePhase, ledgerActions, ledgerStatus, type CasePhase, type LedgerAction } from '../utils/caseLedger'
import { officerDisplayName } from '../utils/officer'

/**
 * 全部案件记录（样板 P20）
 *
 * 台账式列表：关键字 / 状态 / 主审三项筛选，点击行进入案件详情，行内按状态给出办理操作。
 * 新建询问从这里发起（身份录入弹窗），大厅「开始新建笔录」进来时自动打开。
 */
const props = withDefaults(defineProps<{ autoNew?: boolean }>(), { autoNew: false })
const emit = defineEmits<{ open: [caseId: string]; detail: [caseId: string]; created: [caseId: string]; newCancelled: [] }>()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const error = ref('')
const searchTerm = ref('')
const activeQuery = ref('')
const identityOpen = ref(false)
const statusFilter = ref('')
const officerFilter = ref('')
const page = ref(1)
const pageSize = 6
let requestGeneration = 0

function formatTime(timestamp?: number) {
  if (timestamp == null || !Number.isFinite(timestamp)) return '—'
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function isIdentityPrefix(value: string) {
  return /^\d{7,}$/.test(value)
}
function caseTypeLabel(value?: string) {
  return value === 'suspect_interrogation' ? '嫌疑人询问' : value || '未填写'
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
  page.value = 1
  const value = searchTerm.value.trim()
  if (!value) { if (activeQuery.value) void load(); return }
  if (isIdentityPrefix(value)) { void load(value); return }
  if (activeQuery.value) void load()
}
/** 回车 / 搜索：本地已匹配就直接用；本地没有时再按姓名到后端检索更早的案件。 */
function submitSearch() {
  const value = searchTerm.value.trim()
  if (!value) { void load(); return }
  if (isIdentityPrefix(value)) { void load(value); return }
  if (/^\d+$/.test(value) || filteredCases.value.length) return
  void load(value)
}
function clearFilters() {
  searchTerm.value = ''
  statusFilter.value = ''
  officerFilter.value = ''
  page.value = 1
  if (activeQuery.value) void load()
}
function created(item: CaseSummary) {
  identityOpen.value = false
  cases.value = [item, ...cases.value.filter((row) => row.id !== item.id)]
  emit('created', item.id)
}
function closeIntake() {
  identityOpen.value = false
  if (props.autoNew) emit('newCancelled')
}
function runAction(item: CaseSummary, action: LedgerAction) {
  if (action.kind === 'open') emit('open', item.id)
  else if (action.kind === 'detail') emit('detail', item.id)
}

const PHASE_ORDER: CasePhase[] = ['PREPARE', 'IN_PROGRESS', 'REVIEW', 'SIGNING', 'DONE']
const PHASE_LABEL: Record<CasePhase, string> = { PREPARE: '待准备', IN_PROGRESS: '进行中', REVIEW: '待定稿', SIGNING: '待签署 / 已签署', DONE: '已归档' }
const statusFilterOptions = computed<FilterOption[]>(() => PHASE_ORDER.map((key) => ({
  key,
  label: PHASE_LABEL[key],
  count: cases.value.filter((item) => casePhase(item) === key).length,
})))
const officerFilterOptions = computed<FilterOption[]>(() => [...new Set(cases.value.map((item) => item.officerName).filter(Boolean))]
  .sort()
  .map((name) => ({ key: name, label: officerDisplayName(name) || '未指定' })))
/** 关键字在已加载的案件里即时匹配案件编号 / 案由 / 主审民警 / 姓名（样板 P14）；身份证号前缀交给后端检索。 */
const keyword = computed(() => {
  const value = searchTerm.value.trim()
  return value && !isIdentityPrefix(value) ? value.toLowerCase() : ''
})
function matchesKeyword(item: CaseSummary) {
  if (!keyword.value) return true
  return [item.id, caseTypeLabel(item.caseType), item.officerName, item.suspectName]
    .some((field) => (field || '').toLowerCase().includes(keyword.value))
}
const filteredCases = computed(() => cases.value.filter((item) => {
  if (statusFilter.value && casePhase(item) !== statusFilter.value) return false
  if (officerFilter.value && item.officerName !== officerFilter.value) return false
  return matchesKeyword(item)
}))
const pages = computed(() => Math.max(1, Math.ceil(filteredCases.value.length / pageSize)))
const visibleCases = computed(() => filteredCases.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([statusFilter, officerFilter], () => { page.value = 1 })

onMounted(() => {
  void load()
  if (props.autoNew) identityOpen.value = true
})
</script>

<template>
  <section class="case-ledger">
    <header class="ledger-head">
      <div>
        <h1>全部案件记录</h1>
        <p>接入民警认证后本页仅验证后可见 · 点击行进入案件详情</p>
      </div>
      <button type="button" class="ledger-primary" @click="identityOpen = true">＋ 新建询问</button>
    </header>

    <form class="ledger-filters" @submit.prevent="submitSearch">
      <label class="ledger-field ledger-keyword">
        <span>关键字</span>
        <span class="ledger-search"><Search :size="16" aria-hidden="true" /><input v-model="searchTerm" type="search" placeholder="搜索案件编号 / 案由 / 主审民警 / 姓名，或输入身份证号前 7 位" @input="handleSearchInput" /><button type="submit" class="ledger-search-submit">搜索</button></span>
      </label>
      <div class="ledger-field"><span>状态</span><FilterSelect v-model="statusFilter" label="" :options="statusFilterOptions" all-label="全部" /></div>
      <div class="ledger-field"><span>主审</span><FilterSelect v-model="officerFilter" label="" :options="officerFilterOptions" all-label="全部" /></div>
    </form>

    <section class="ledger-table-shell">
      <table class="case-dashboard-table">
        <thead>
          <tr><th>案件编号</th><th>案由</th><th>状态</th><th>主审</th><th>更新时间</th><th>操作</th></tr>
        </thead>
        <tbody v-if="!loading && !error && visibleCases.length">
          <tr v-for="item in visibleCases" :key="item.id" tabindex="0" @click="emit('detail', item.id)" @keydown.enter="emit('detail', item.id)">
            <td class="ledger-id">案 {{ item.id }}</td>
            <td>{{ caseTypeLabel(item.caseType) }}<small v-if="item.suspectName"> · {{ item.suspectName }}</small></td>
            <td><span class="case-status" :class="`is-${casePhase(item).toLowerCase()}`">{{ ledgerStatus(item) }}</span></td>
            <td :class="{ 'ledger-muted': !officerDisplayName(item.officerName) }">{{ officerDisplayName(item.officerName) || '未指定' }}</td>
            <td>{{ formatTime(item.updatedAt) }}</td>
            <td class="ledger-actions">
              <button
                v-for="action in ledgerActions(item)"
                :key="action.label"
                type="button"
                :disabled="action.kind === 'pending'"
                :title="action.kind === 'pending' ? '功能待接入' : undefined"
                @click.stop="runAction(item, action)"
              >{{ action.label }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="loading" class="ledger-state" role="status">正在读取案件…</div>
      <EmptyState v-else-if="error" kind="error" :description="error" @retry="load(activeQuery)" />
      <EmptyState v-else-if="!filteredCases.length" kind="empty" title="暂无匹配记录" description="当前筛选条件下没有案件，可清空筛选或新建询问">
        <button type="button" @click="clearFilters">清空筛选条件</button>
      </EmptyState>
      <footer v-if="filteredCases.length" class="ledger-footer">
        <span>共 {{ cases.length }} 起 · 当前筛选显示 {{ filteredCases.length }} 条 · 每页 {{ pageSize }} 条</span>
        <span class="ledger-pager">
          <button type="button" :disabled="page <= 1" @click="page -= 1"><ChevronLeft :size="15" aria-hidden="true" />上一页</button>
          <b>{{ page }} / {{ pages }}</b>
          <button type="button" :disabled="page >= pages" @click="page += 1">下一页<ChevronRight :size="15" aria-hidden="true" /></button>
        </span>
      </footer>
    </section>

    <IdentityIntakeModal v-if="identityOpen" @close="closeIntake" @created="created" />
  </section>
</template>

<style scoped>
.case-ledger { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.ledger-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.ledger-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.ledger-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.ledger-primary { min-height: 44px; padding: 0 var(--space-5); border: 0; border-radius: var(--radius-md); background: var(--primary-600); color: var(--surface); font-size: var(--text-base); font-weight: 600; }

.ledger-filters { display: grid; grid-template-columns: minmax(0, 2fr) minmax(160px, 1fr) minmax(160px, 1fr) 1fr; gap: var(--space-4); align-items: end; }
.ledger-field { display: flex; flex-direction: column; gap: var(--space-1); color: var(--ink-500); font-size: var(--text-xs); }
.ledger-search { display: flex; align-items: center; gap: var(--space-2); min-height: 44px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--ink-400); }
.ledger-search input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--ink-900); font-size: var(--text-sm); outline: none; }
.ledger-search-submit { min-height: 36px; margin-right: calc(-1 * var(--space-2)); padding: 0 var(--space-4); border: 0; border-radius: var(--radius-sm); background: var(--primary-600); color: var(--surface); font-size: var(--text-sm); font-weight: 600; }
/* 筛选触发器撑满所在列，展开浮层与触发器同宽（走查 D31） */
.ledger-field :deep(.filter-select) { width: 100%; }
.ledger-field :deep(.filter-trigger) { width: 100%; min-height: 44px; }
.ledger-field :deep(.filter-chevron) { margin-left: auto; }
.ledger-field :deep(.filter-panel) { width: 100%; }

.ledger-table-shell { display: flex; flex-direction: column; border-radius: var(--radius-lg); background: var(--surface); overflow: hidden; }
.case-dashboard-table { width: 100%; border-collapse: collapse; text-align: left; font-size: var(--text-sm); }
.case-dashboard-table th { padding: var(--space-3) var(--space-4); background: var(--primary-50); color: var(--ink-500); font-size: var(--text-xs); font-weight: 600; white-space: nowrap; }
.case-dashboard-table td { height: 60px; padding: 0 var(--space-4); border-bottom: 1px solid var(--line-100); color: var(--ink-700); white-space: nowrap; }
.case-dashboard-table tbody tr { cursor: pointer; }
.case-dashboard-table tbody tr:hover { background: var(--surface-sunken); }
.case-dashboard-table small { color: var(--ink-400); }
.case-dashboard-table td.ledger-muted { color: var(--ink-400); }
.ledger-id { color: var(--ink-900); font-weight: 600; }
.ledger-actions { display: flex; align-items: center; gap: var(--space-2); height: 60px; }
.ledger-actions button { min-height: 32px; padding: 0 var(--space-2); border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-sm); }
.ledger-state { padding: var(--space-6); color: var(--ink-400); text-align: center; font-size: var(--text-sm); }
.ledger-table-shell :deep(.empty-state) { padding: var(--space-5); }
.ledger-footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-3) var(--space-4); color: var(--ink-400); font-size: var(--text-xs); }
.ledger-pager { display: flex; align-items: center; gap: var(--space-3); }
.ledger-pager button { display: inline-flex; align-items: center; gap: 2px; min-height: 32px; border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-xs); }
.ledger-pager b { color: var(--ink-900); }
@media (max-width: 900px) { .ledger-filters { grid-template-columns: 1fr; } }
</style>
