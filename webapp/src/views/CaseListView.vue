<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { backendErrorMessage, fetchCases } from '../api/interrogation'
import IdentityIntakeModal from '../components/IdentityIntakeModal.vue'
import type { CaseSummary } from '../types/interrogation'

interface CaseRow extends CaseSummary {}

const stateTextMap: Record<string, string> = {
  DRAFT: '草稿',
  INTERROGATING: '审讯中',
  REVIEWING: '复核中',
  SIGNING: '签名中',
  COMPLETED: '已完成',
  ARCHIVED: '已归档',
}
const stageTextMap: Record<string, string> = {
  IDENTITY: '身份核验',
  STATEMENT: '案情陈述',
  FOLLOW_UP: '重点追问',
  SIGNING: '确认签名',
}

const emit = defineEmits<{ open: [caseId: string] }>()
const loading = ref(true)
const error = ref('')
const cases = ref<CaseRow[]>([])
const identityOpen = ref(false)
const searchTerm = ref('')
const activeQuery = ref('')
let requestGeneration = 0

function fmtTime(ts?: number) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function maskedId(idNumber?: string) {
  if (!idNumber) return ''
  if (idNumber.length < 8) return idNumber
  return `${idNumber.slice(0, 3)}***********${idNumber.slice(-4)}`
}

function identitySourceText(source?: string) {
  if (source === 'ID_CARD_READER') return '读卡器身份'
  if (source === 'OCR') return 'OCR 身份'
  if (source === 'MANUAL') return '人工身份'
  return source || ''
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
    const result = await fetchCases(query ? 100 : 50, query)
    if (generation !== requestGeneration) return
    cases.value = result
  } catch (err) {
    if (generation !== requestGeneration) return
    error.value = backendErrorMessage(err)
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

function handleSearchInput() {
  const value = searchTerm.value.trim()
  if (!value) {
    void load()
    return
  }
  if (isIdentityPrefix(value)) {
    void load(value)
    return
  }
  if (activeQuery.value) void load()
}

function submitSearch() {
  const value = searchTerm.value.trim()
  if (!value) {
    void load()
    return
  }
  if (/^\d+$/.test(value) && !isIdentityPrefix(value)) return
  void load(value)
}

async function created(item: CaseSummary) {
  identityOpen.value = false
  error.value = ''
  cases.value = [item, ...cases.value.filter((row) => row.id !== item.id)]
  emit('open', item.id)
}

onMounted(load)
</script>

<template>
  <main class="case-list-page">
    <header class="case-list-header">
      <div class="system-title">
        <span>公安业务终端</span>
        <h1>嫌疑人询问系统</h1>
        <p>案件历史记录与询问入口</p>
      </div>
      <div class="case-list-actions">
        <div class="case-count"><strong>{{ cases.length }}</strong><span>案件总数</span></div>
        <button class="btn-primary" @click="identityOpen = true">＋ 新建询问</button>
      </div>
    </header>

    <section class="case-list-toolbar">
      <div>
        <strong>案件列表</strong>
        <span>选择案件进入工作台，或新建询问后先完成身份核验</span>
      </div>
      <form class="case-search" @submit.prevent="submitSearch">
        <input
          v-model="searchTerm"
          aria-label="按姓名或身份证搜索"
          placeholder="输入完整姓名，或身份证前 7 位"
          @input="handleSearchInput"
        />
        <button type="submit" :disabled="loading || !searchTerm.trim()">查询</button>
      </form>
      <button class="refresh-button" :disabled="loading" @click="load()">{{ loading ? '刷新中…' : '刷新列表' }}</button>
    </section>

    <div v-if="loading" class="status-banner">正在加载案件历史…</div>
    <div v-else-if="error" class="status-banner error">{{ error }}</div>
    <div v-else-if="!cases.length" class="empty-state">
      <strong>暂无案件记录</strong>
      <p>点击右上角“新建询问”，先读取并核对身份证，再进入案件工作台。</p>
      <button class="btn-primary" @click="identityOpen = true">新建第一起询问</button>
    </div>

    <section v-else class="case-list" aria-label="案件列表">
      <button v-for="item in cases" :key="item.id" class="case-row" type="button" @click="emit('open', item.id)">
        <div class="person-cell">
          <div class="person-avatar">{{ (item.suspectName || '待')[0] }}</div>
          <div>
            <div class="case-row-title">
              <strong>{{ item.suspectName || '待录入人员' }}</strong>
              <span v-if="item.gender || item.age">{{ item.gender || '' }} {{ item.age ? `${item.age}岁` : '' }}</span>
            </div>
            <small v-if="item.idNumber">身份证：{{ maskedId(item.idNumber) }}</small>
            <small v-else>身份证：未录入</small>
          </div>
        </div>

        <div class="case-info-cell">
          <span>案件编号</span>
          <strong>{{ item.id }}</strong>
        </div>
        <div class="case-info-cell">
          <span>主审民警</span>
          <strong>{{ item.officerName || '当前警官' }}</strong>
        </div>
        <div class="case-info-cell">
          <span>最后更新</span>
          <strong>{{ fmtTime(item.updatedAt) || '暂无' }}</strong>
        </div>

        <div class="case-status-cell">
          <span v-if="item.identitySource" class="tag identity">{{ identitySourceText(item.identitySource) }}</span>
          <span class="tag stage">{{ stageTextMap[item.stage] || item.stage }}</span>
          <span class="tag state" :data-state="item.state">{{ stateTextMap[item.state] || item.state }}</span>
        </div>
        <span class="enter-arrow">进入 ›</span>
      </button>
    </section>
  </main>

  <IdentityIntakeModal v-if="identityOpen" @close="identityOpen = false" @created="created" />
</template>

<style scoped>
.case-list-page {
  --list-blue: var(--primary-700);
  --list-accent: var(--primary-600);
  --list-line: var(--primary-200);
  width: 100%;
  min-width: 1320px;
  height: 100vh;
  display: grid;
  grid-template-rows: 94px 64px minmax(0, 1fr);
  overflow: hidden;
  background: var(--primary-100);
  color: var(--navy-900);
}
.case-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  padding: 0 32px;
  background: var(--navy-900);
  color: var(--surface);
  border-bottom: 4px solid var(--warning-600);
}
.system-title > span { display: block; color: var(--ink-300); font-size: 12px; letter-spacing: .14em; }
.system-title h1 { margin: 3px 0 2px; font-size: 25px; letter-spacing: .04em; }
.system-title p { margin: 0; color: var(--primary-200); font-size: 13px; }
.case-list-actions { display: flex; align-items: center; gap: 18px; }
.case-count { min-width: 94px; display: flex; align-items: baseline; justify-content: center; gap: 7px; padding: 8px 12px; border: 1px solid var(--ink-500); background: var(--navy-900); }
.case-count strong { font-size: 22px; }
.case-count span { color: var(--line-300); font-size: 12px; }
.btn-primary, .refresh-button {
  min-height: 50px;
  border: 1px solid var(--ink-300);
  border-radius: 5px;
  padding: 0 20px;
  background: var(--surface);
  color: var(--ink-700);
  font-size: 15px;
  font-weight: 700;
  touch-action: manipulation;
}
.btn-primary { min-width: 170px; border-color: var(--primary-600); background: var(--primary-600); color: var(--surface); }
.case-list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 32px;
  border-bottom: 1px solid var(--list-line);
  background: var(--surface-sunken);
}
.case-list-toolbar > div { display: flex; align-items: baseline; gap: 14px; }
.case-list-toolbar strong { color: var(--ink-700); font-size: 18px; }
.case-list-toolbar span { color: var(--ink-400); font-size: 13px; }
.case-search { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.case-search input { width: 320px; min-height: 40px; box-sizing: border-box; border: 1px solid var(--ink-300); border-radius: 4px; padding: 0 12px; color: var(--ink-700); font: inherit; }
.case-search button { min-height: 40px; border: 1px solid var(--primary-600); border-radius: 4px; padding: 0 17px; background: var(--primary-600); color: var(--surface); font: inherit; font-weight: 700; touch-action: manipulation; }
.refresh-button { min-width: 112px; min-height: 44px; }
.status-banner { margin: 18px 32px; padding: 18px; border: 1px solid var(--primary-200); background: var(--surface-sunken); text-align: center; color: var(--ink-500); }
.status-banner.error { border-color: var(--danger-100); background: var(--danger-100); color: var(--danger-600); }
.empty-state { align-self: center; justify-self: center; width: 520px; padding: 42px; text-align: center; border: 1px solid var(--primary-200); background: var(--surface); }
.empty-state strong { display: block; color: var(--ink-700); font-size: 20px; }
.empty-state p { margin: 12px 0 22px; color: var(--ink-400); line-height: 1.7; }
.case-list { min-height: 0; overflow: auto; padding: 18px 32px 30px; }
.case-row {
  width: 100%;
  min-height: 104px;
  display: grid;
  grid-template-columns: minmax(280px, 1.25fr) minmax(180px, .8fr) minmax(130px, .55fr) minmax(160px, .7fr) minmax(330px, 1.3fr) 76px;
  align-items: center;
  gap: 18px;
  margin: 0 0 10px;
  padding: 12px 18px;
  border: 1px solid var(--primary-200);
  border-left: 5px solid var(--ink-500);
  border-radius: 4px;
  background: var(--surface);
  color: var(--ink-700);
  text-align: left;
  font: inherit;
  touch-action: manipulation;
}
.case-row:focus-visible { outline: 3px solid rgba(31,101,151,.25); outline-offset: 2px; }
.person-cell { min-width: 0; display: grid; grid-template-columns: 58px minmax(0,1fr); align-items: center; gap: 12px; }
.person-avatar { width: 58px; height: 66px; display: grid; place-items: center; border: 1px solid var(--ink-400); background: var(--primary-100); color: var(--ink-500); font-size: 22px; font-weight: 700; }
.case-row-title { display: flex; align-items: baseline; gap: 9px; }
.case-row-title strong { color: var(--ink-700); font-size: 18px; }
.case-row-title span, .person-cell small { color: var(--ink-400); font-size: 12px; }
.person-cell small { display: block; margin-top: 6px; }
.case-info-cell { min-width: 0; display: grid; gap: 7px; }
.case-info-cell span { color: var(--ink-400); font-size: 11px; }
.case-info-cell strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--ink-700); font-size: 13px; white-space: nowrap; }
.case-status-cell { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; justify-content: flex-end; }
.tag { padding: 6px 9px; border: 1px solid var(--primary-200); border-radius: 3px; background: var(--surface-sunken); color: var(--ink-500); font-size: 11px; font-weight: 700; white-space: nowrap; }
.tag.identity { border-color: var(--success-100); background: var(--success-100); color: var(--success-700); }
.tag.stage { border-color: var(--ink-300); background: var(--surface-sunken); color: var(--primary-600); }
.tag.state[data-state="INTERROGATING"] { border-color: var(--warning-600); background: var(--warning-100); color: var(--warning-700); }
.tag.state[data-state="REVIEWING"], .tag.state[data-state="COMPLETED"] { border-color: var(--success-100); background: var(--success-100); color: var(--success-700); }
.tag.state[data-state="DRAFT"] { border-color: var(--line-300); background: var(--surface-sunken); color: var(--ink-500); }
.enter-arrow { justify-self: end; color: var(--primary-600); font-size: 14px; font-weight: 700; white-space: nowrap; }
button:disabled { opacity: .48; cursor: not-allowed; }
</style>
