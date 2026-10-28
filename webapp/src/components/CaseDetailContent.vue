<script setup lang="ts">
import { computed } from 'vue'
import { Check } from '@lucide/vue'
import type { CaseSummary, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { coreFacts, factCoverage } from '../utils/factCoverage'
import { formatRecordTime } from '../utils/recordPaper'
import EmptyState from './EmptyState.vue'
import RecordPaper from './RecordPaper.vue'
import { officerDisplayName } from '../utils/officer'

/**
 * 案件详情（样板 P21 / P22）：笔录与卷宗信息、要素覆盖、录音与文书预览集中在一页。
 * 已归档案件只读；未归档案件可继续办理，并列出缺项。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  signingState: DocumentSigningState | null
}>()
const emit = defineEmits<{ open: [caseId: string] }>()

const archived = computed(() => props.summary.workflowState === 'REPORT_GENERATED')
const coverage = computed(() => factCoverage(props.facts))
const elements = computed(() => coreFacts(props.facts))
const maskedId = computed(() => {
  const id = props.summary.idNumber || ''
  return id.length >= 8 ? `${id.slice(0, 4)}${'*'.repeat(id.length - 8)}${id.slice(-4)}` : id || '未填写'
})
const caseTypeText = computed(() => (props.summary.caseType === 'suspect_interrogation' ? '嫌疑人询问' : props.summary.caseType || '未填写'))
</script>

<template>
  <section class="case-detail">
    <header class="case-detail-head">
      <div>
        <h1>案件详情 · 案 {{ summary.id }} {{ caseTypeText }}</h1>
        <p>{{ archived ? `已归档 ${formatRecordTime(summary.updatedAt)} · 笔录只读` : '未归档 · 可继续办理或补录，标注缺项原因后再定稿' }}</p>
      </div>
      <div class="case-detail-actions">
        <button type="button" class="detail-secondary" disabled title="功能待接入">查看本笔录录音</button>
        <button type="button" class="detail-secondary" disabled title="功能待接入">导出 Word</button>
        <button type="button" class="detail-secondary" disabled title="功能待接入">导出 PDF</button>
        <button v-if="!archived" type="button" class="detail-primary" @click="emit('open', summary.id)">继续办理</button>
      </div>
    </header>

    <div class="case-detail-body">
      <article class="detail-card">
        <h2>笔录与卷宗信息</h2>
        <dl>
          <div><dt>被询问人</dt><dd>{{ summary.suspectName || '未填写' }} · {{ summary.gender || '未填写' }} · {{ maskedId }}</dd></div>
          <div><dt>询问人</dt><dd>{{ officerDisplayName(summary.officerName) || '未指定' }}</dd></div>
          <div><dt>文书</dt><dd>询问笔录（要素 {{ coverage.covered }}/{{ coverage.total }} 覆盖）· 签名 {{ signingState?.signatures.length ?? 0 }} 处</dd></div>
          <div><dt>录音</dt><dd><EmptyState kind="pending" title="录音查看" /></dd></div>
          <div><dt>导出记录</dt><dd>功能待接入</dd></div>
        </dl>
        <section class="detail-coverage">
          <h3>要素覆盖 {{ coverage.covered }} / {{ coverage.total }} 清单</h3>
          <ul>
            <li v-for="(item, index) in elements" :key="item.key" :class="{ ok: item.status === 'confirmed' }">
              {{ index + 1 }} {{ item.label }}<Check v-if="item.status === 'confirmed'" :size="13" aria-hidden="true" />
            </li>
          </ul>
          <p v-if="!archived && coverage.missing.length" class="detail-missing">缺项：{{ coverage.missing.map((item) => item.label).join('、') }}</p>
        </section>
      </article>

      <article class="detail-card detail-preview">
        <h2>文书预览</h2>
        <RecordPaper :summary="summary" :facts="facts" :session="session" :questions="questions">
          <template #footer>
            <footer class="detail-signatures">
              <span v-for="item in signingState?.signatures ?? []" :key="item.signerRole">
                {{ item.signerRole === 'SUSPECT' ? '被询问人' : '询问人' }}签名：<img :src="item.imageDataUrl" :alt="`${item.signerName}签名`" />
              </span>
              <small v-if="!signingState?.signatures.length">尚无签名</small>
            </footer>
          </template>
        </RecordPaper>
      </article>
    </div>
  </section>
</template>

<style scoped>
.case-detail { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.case-detail-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
.case-detail-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.case-detail-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.case-detail-actions { display: flex; gap: var(--space-2); }
.detail-primary, .detail-secondary { min-height: 40px; padding: 0 var(--space-4); border-radius: var(--radius-sm); font-size: var(--text-sm); font-weight: 600; }
.detail-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.detail-secondary { border: 1px solid var(--primary-500); background: var(--surface); color: var(--primary-600); }
.case-detail-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.detail-card { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.detail-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 600; }
.detail-card dl { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; font-size: var(--text-sm); }
.detail-card dl div { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: var(--space-3); }
.detail-card dt { color: var(--ink-500); }
.detail-card dd { margin: 0; color: var(--ink-700); }
.detail-coverage { padding: var(--space-4); border-radius: var(--radius-md); background: var(--surface-sunken); }
.detail-coverage h3 { margin: 0 0 var(--space-2); color: var(--ink-900); font-size: var(--text-sm); }
.detail-coverage ul { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-4); margin: 0; padding: 0; list-style: none; color: var(--ink-500); font-size: var(--text-xs); }
.detail-coverage li { display: inline-flex; align-items: center; gap: 2px; }
.detail-coverage li.ok { color: var(--success-700); }
.detail-missing { margin: var(--space-2) 0 0; color: var(--warning-700); font-size: var(--text-xs); }
.detail-preview :deep(.record-paper) { padding: var(--space-5); border: 1px solid var(--line-200); border-radius: var(--radius-md); font-size: var(--text-sm); }
.detail-signatures { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-top: var(--space-4); font-size: var(--text-xs); }
.detail-signatures img { max-height: 48px; vertical-align: middle; }
.detail-signatures small { color: var(--paper-muted); }
@media (max-width: 1100px) { .case-detail-body { grid-template-columns: 1fr; } }
</style>
