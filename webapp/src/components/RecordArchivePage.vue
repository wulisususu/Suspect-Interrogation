<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, FileCheck2, FileDown, Printer } from '@lucide/vue'
import type { CaseSummary, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { branding } from '../config/branding'
import { factValue, formatRecordTime, recordWordCount, volumeNumber } from '../utils/recordPaper'
import { factCoverage } from '../utils/factCoverage'
import RecordPaper from './RecordPaper.vue'

/**
 * ⑥ 归档导出
 *
 * 主线终点：确认归档后这里给出正式件信息，并提供两种导出——
 * PDF 走打印视图（含签章，与屏上文书逐字一致），Word 走纯文字版（可二次编辑）。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  signingState: DocumentSigningState | null
  archivedAt?: number | null
}>()

const emit = defineEmits<{ print: []; back: [] }>()

const questions = computed(() => [...props.questions].sort((a, b) => a.sortOrder - b.sortOrder))
const wordCount = computed(() => recordWordCount(props.questions))
const volumeNo = computed(() => volumeNumber(branding.volumePrefix, props.summary.id || ''))
const archivedText = computed(() => {
  const stamp = props.archivedAt || props.summary.updatedAt || props.summary.createdAt
  return stamp ? new Date(stamp).toLocaleString('zh-CN', { hour12: false }) : '—'
})
const signedCount = computed(() => props.signingState?.signatures.length ?? 0)
const coverage = computed(() => factCoverage(props.facts))

const fact = (key: string) => factValue(props.facts, key)
const time = formatRecordTime

/** 纯文字版：给二次编辑用，保留问答结构，不带签章图片 */
function exportWord() {
  const head = `<p>询问时间：${time(props.session.startedAt || props.summary.createdAt)} 至 ${time(props.session.endedAt)}</p>`
    + `<p>询问地点：${fact('interrogation_place')}</p>`
    + `<p>询问人：${props.summary.officerName || '未填写'}　记录人：${fact('recorder_name')}</p>`
    + `<p>被询问人：${props.summary.suspectName || '未填写'}　证件号码：${props.summary.idNumber || '未填写'}</p>`
    + `<p>案件编号：${props.summary.id}　卷号：${volumeNo.value}</p>`
  const body = questions.value
    .map((question) => `<p>问：${escapeHtml(question.text)}</p><p>答：${escapeHtml(question.formalAnswerText || '（未获取）')}</p>`)
    .join('')
  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">`
    + `<head><meta charset="utf-8"><title>询问笔录</title></head>`
    + `<body style="font-family:'仿宋',SimSun,serif;font-size:12pt;line-height:1.8">`
    + `<h1 style="text-align:center;letter-spacing:4px">询 问 笔 录</h1>${head}<hr/>${body}</body></html>`

  const blob = new Blob([`\ufeff${html}`], { type: 'application/msword' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.summary.id}-询问笔录.doc`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char] || char))
}
</script>

<template>
  <section class="record-archive">
    <header class="archive-head record-no-print">
      <div>
        <h1>归档结果 · 办结</h1>
        <p>《询问笔录》已登记入卷 · 笔录转为只读，如需更正只能作废重做</p>
      </div>
      <button type="button" class="archive-back" @click="emit('back')"><ArrowLeft :size="16" aria-hidden="true" />返回案件台账</button>
    </header>

    <section class="archive-result record-no-print" aria-label="归档结果">
      <span class="archive-result-icon" aria-hidden="true"><FileCheck2 :size="40" /></span>
      <div class="archive-result-main">
        <h2>归档成功 · 办结</h2>
        <p>案 {{ summary.id }} · 《询问笔录》已登记入卷 · 要素 {{ coverage.covered }}/{{ coverage.total }} 覆盖 · 签章 {{ signedCount }} 处</p>
        <dl class="archive-tiles">
          <div><dt>卷　号</dt><dd>{{ volumeNo }}</dd></div>
          <div><dt>归档人 · 时间</dt><dd>{{ summary.officerName || '未指定' }} · {{ archivedText }}</dd></div>
          <div class="is-ok"><dt>签　章</dt><dd>签名 {{ signedCount }} 处 · 指纹按纸质件</dd></div>
          <div><dt>录音 · 文书</dt><dd>{{ wordCount }} 字 · {{ questions.length }} 题 · 冻结版本 {{ signingState?.version ?? '—' }}</dd></div>
        </dl>
      </div>
    </section>

    <div class="archive-exports record-no-print">
      <section class="archive-export">
        <header><span class="archive-export-badge">W</span><h2>导出 Word</h2><small>轻量编辑版</small></header>
        <p>适合二次编辑、摘录与转发的轻量版本 · .doc</p>
        <ul>
          <li>✓ 全文纯文字，保留问答结构</li>
          <li>✓ 不含手写签章与指纹</li>
          <li>✓ 适合二次编辑与摘录</li>
        </ul>
        <button type="button" class="archive-secondary" @click="exportWord"><FileDown :size="17" aria-hidden="true" />导出 Word</button>
      </section>
      <section class="archive-export is-primary">
        <header><span class="archive-export-badge">PDF</span><h2>导出 PDF</h2><small>归档正式件</small></header>
        <p>归档正式件，用于长期保存与卷宗移交 · .pdf</p>
        <ul>
          <li>✓ 含已完成的电子签名</li>
          <li>✓ 与打印件、屏上文书一致</li>
          <li>✓ 在打印对话框中选择「另存为 PDF」</li>
        </ul>
        <button type="button" class="archive-primary" @click="emit('print')"><Printer :size="17" aria-hidden="true" />导出 PDF</button>
      </section>
    </div>

    <p class="archive-footnote record-no-print">已归档笔录只读 · 如需更正只能作废重做</p>

    <div class="archive-print-only">
      <RecordPaper class="archive-paper" :summary="summary" :facts="facts" :session="session" :questions="questions" :subtitle="`归档正式件 · ${branding.volumePrefix ? `卷号 ${volumeNo}` : volumeNo}`">
        <template #footer>
        <footer class="archive-signatures">
          <div v-for="role in (['SUSPECT', 'OFFICER'] as const)" :key="role" class="archive-signature">
            <span>{{ role === 'SUSPECT' ? '被询问人签名：' : '询问人签名：' }}</span>
            <img
              v-if="signingState?.signatures.find((item) => item.signerRole === role)"
              :src="signingState.signatures.find((item) => item.signerRole === role)!.imageDataUrl"
              :alt="role === 'SUSPECT' ? '被询问人签名' : '询问人签名'"
            />
            <span v-else>____________</span>
          </div>
          <p>指纹捺印按纸质件办理 · 冻结版本 {{ signingState?.version ?? '—' }}</p>
        </footer>
        </template>
      </RecordPaper>
    </div>
  </section>
</template>

<style scoped>
.record-archive { display: flex; flex-direction: column; gap: var(--space-5); min-height: 0; height: 100%; overflow: auto; color: var(--ink-700); }
.archive-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.archive-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 650; }
.archive-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.archive-back { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 44px; padding: 0 var(--space-4); border: 1px solid var(--primary-500); border-radius: var(--radius-md); background: var(--surface); color: var(--primary-600); font-size: var(--text-sm); font-weight: 600; }

.archive-result { display: flex; gap: var(--space-5); padding: var(--space-6); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); }
.archive-result-icon { display: grid; place-items: center; width: 80px; height: 80px; flex: none; border: 1px solid var(--success-600); border-radius: var(--radius-lg); background: var(--success-100); color: var(--success-700); }
.archive-result-main { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; flex: 1; }
.archive-result-main h2 { margin: 0; color: var(--success-700); font-size: var(--text-2xl); font-weight: 650; }
.archive-result-main p { margin: 0; color: var(--ink-700); font-size: var(--text-sm); }
.archive-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); margin: var(--space-2) 0 0; }
.archive-tiles div { padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--surface-sunken); }
.archive-tiles div.is-ok { background: var(--success-100); }
.archive-tiles dt { color: var(--ink-400); font-size: var(--text-xs); }
.archive-tiles dd { margin: var(--space-1) 0 0; color: var(--ink-900); font-size: var(--text-sm); font-weight: 600; overflow-wrap: anywhere; }
.archive-tiles div.is-ok dd { color: var(--success-700); }

.archive-exports { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-5); }
.archive-export { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-6); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); }
.archive-export.is-primary { border-color: var(--primary-500); }
.archive-export header { display: flex; align-items: center; gap: var(--space-3); }
.archive-export h2 { margin: 0; color: var(--ink-900); font-size: var(--text-xl); font-weight: 600; }
.archive-export small { padding: 2px var(--space-2); border-radius: var(--radius-sm); background: var(--primary-100); color: var(--primary-600); font-size: var(--text-xs); }
.archive-export-badge { display: grid; place-items: center; width: 44px; height: 44px; border-radius: var(--radius-md); background: var(--primary-100); color: var(--primary-600); font-weight: 700; }
.archive-export p { margin: 0; color: var(--ink-500); font-size: var(--text-sm); }
.archive-export ul { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; padding: 0 0 var(--space-3); list-style: none; border-bottom: 1px solid var(--line-200); font-size: var(--text-sm); }
.archive-primary, .archive-secondary { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 48px; border-radius: var(--radius-md); font-size: var(--text-md); font-weight: 600; }
.archive-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.archive-secondary { border: 1px solid var(--primary-500); background: var(--surface); color: var(--primary-600); }
.archive-footnote { margin: 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-xs); }

.archive-print-only { display: none; }
.archive-paper { width: 794px; margin: 0 auto; }
.archive-signatures { margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--paper-rule); }
.archive-signature { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; min-height: 40px; }
.archive-signature img { max-width: 200px; max-height: 70px; object-fit: contain; }
.archive-signatures > p { margin: 0; color: var(--paper-muted); font: var(--text-xs)/1.7 var(--font-sans); }

@media (max-width: 1100px) { .archive-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } .archive-exports { grid-template-columns: 1fr; } }
@media print {
  .record-archive { display: block; height: auto; overflow: visible; }
  .archive-print-only { display: block; }
}
</style>
