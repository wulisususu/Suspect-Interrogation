<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchDocumentSigningState } from '../api/documentSigning'
import { backendErrorMessage, fetchCase, fetchFacts, fetchSessionState } from '../api/interrogation'
import { fetchTemplateWorkspace } from '../api/templateInterrogation'
import CaseDetailContent from '../components/CaseDetailContent.vue'
import EmptyState from '../components/EmptyState.vue'
import type { CaseSummary, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/** 案件详情页：只读加载案件、事实、会话、文书与签名，交给 CaseDetailContent 展示。 */
const props = defineProps<{ caseId: string }>()
const emit = defineEmits<{ open: [caseId: string] }>()

const loading = ref(true)
const error = ref('')
const data = ref<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  signingState: DocumentSigningState | null
} | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [summary, facts, session, workspace, signingState] = await Promise.all([
      fetchCase(props.caseId),
      fetchFacts(props.caseId),
      fetchSessionState(props.caseId),
      fetchTemplateWorkspace(props.caseId),
      fetchDocumentSigningState(props.caseId),
    ])
    data.value = { summary, facts, session, questions: workspace.questions, signingState }
  } catch (cause) {
    error.value = backendErrorMessage(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <p v-if="loading" class="detail-loading" role="status">正在读取案件详情…</p>
  <EmptyState v-else-if="error || !data" kind="error" :description="error || '案件不存在'" @retry="load" />
  <CaseDetailContent v-else v-bind="data" @open="emit('open', $event)" />
</template>

<style scoped>
.detail-loading { margin: var(--space-10) 0; color: var(--ink-400); text-align: center; font-size: var(--text-sm); }
</style>
