<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { backendErrorMessage, fetchCases } from '../api/interrogation'
import EmptyState from '../components/EmptyState.vue'
import PendingCaseList from '../components/PendingCaseList.vue'
import type { CaseSummary } from '../types/interrogation'

const emit = defineEmits<{ open: [caseId: string]; detail: [caseId: string] }>()
const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try { cases.value = await fetchCases(200) }
  catch (cause) { error.value = backendErrorMessage(cause) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <p v-if="loading" class="admin-loading" role="status">正在读取未完成办理…</p>
  <EmptyState v-else-if="error" kind="error" :description="error" @retry="load" />
  <PendingCaseList v-else :cases="cases" @open="emit('open', $event)" @detail="emit('detail', $event)" />
</template>

<style scoped>
.admin-loading { margin: var(--space-10) 0; color: var(--ink-400); text-align: center; font-size: var(--text-sm); }
</style>
