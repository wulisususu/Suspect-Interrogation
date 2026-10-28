<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { fetchCaseAudit, type AuditEntry } from '../api/audit'
import { backendErrorMessage, fetchCases } from '../api/interrogation'
import AuditLogTable from '../components/AuditLogTable.vue'
import EmptyState from '../components/EmptyState.vue'
import FilterSelect, { type FilterOption } from '../components/FilterSelect.vue'
import type { CaseSummary } from '../types/interrogation'

/** 操作日志（样板 P29）：按案件查看后端审计记录。 */
const cases = ref<CaseSummary[]>([])
const caseId = ref('')
const entries = ref<AuditEntry[]>([])
const error = ref('')
let request = 0

const caseOptions = computed<FilterOption[]>(() => cases.value.map((item) => ({ key: item.id, label: `案 ${item.id}${item.suspectName ? ` · ${item.suspectName}` : ''}` })))

async function loadCases() {
  try { cases.value = await fetchCases(200) }
  catch (cause) { error.value = backendErrorMessage(cause) }
}
async function loadEntries() {
  const current = ++request
  entries.value = []
  error.value = ''
  if (!caseId.value) return
  try {
    const rows = await fetchCaseAudit(caseId.value)
    if (current === request) entries.value = rows.sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
  } catch (cause) {
    if (current === request) error.value = backendErrorMessage(cause)
  }
}
watch(caseId, loadEntries)
onMounted(loadCases)
</script>

<template>
  <section class="audit-page">
    <header>
      <h1>操作日志</h1>
      <p>全部操作留痕 · 只读留置、不可删除，随案归档并与文书内容互相溯源</p>
    </header>
    <div class="audit-filter"><span>案件</span><FilterSelect v-model="caseId" label="" :options="caseOptions" all-label="请选择案件" /></div>
    <EmptyState v-if="error" kind="error" :description="error" @retry="caseId ? loadEntries() : loadCases()" />
    <AuditLogTable v-else :entries="entries" :case-selected="Boolean(caseId)" />
  </section>
</template>

<style scoped>
.audit-page { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.audit-page header h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.audit-page header p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.audit-filter { display: flex; align-items: center; gap: var(--space-3); color: var(--ink-500); font-size: var(--text-sm); }
</style>
