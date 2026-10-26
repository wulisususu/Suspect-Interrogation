<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, FileDown, Printer } from '@lucide/vue'
import type { CaseSummary, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { branding } from '../config/branding'
import { factValue, formatRecordTime, recordWordCount, volumeNumber } from '../utils/recordPaper'
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
    <div class="archive-preview">
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

    <aside class="archive-side">
      <section class="archive-card">
        <header><h2>归档结果</h2><span class="archive-done">已办结</span></header>
        <dl>
          <div><dt>案号</dt><dd>{{ summary.id }}</dd></div>
          <div><dt>卷号</dt><dd>{{ volumeNo }}</dd></div>
          <div><dt>归档人</dt><dd>{{ summary.officerName || '未指定' }}</dd></div>
          <div><dt>归档时间</dt><dd>{{ archivedText }}</dd></div>
          <div><dt>签章</dt><dd class="ok">{{ signedCount }} 处</dd></div>
          <div><dt>文书</dt><dd>{{ wordCount }} 字 · {{ questions.length }} 题</dd></div>
          <div><dt>完整性</dt><dd :class="{ ok: signingState?.integrityValid }">{{ signingState?.integrityValid ? '校验通过' : '未校验' }}</dd></div>
        </dl>
        <p class="archive-note">归档后笔录转为只读，可在案件台账中随时查阅。</p>
      </section>

      <section class="archive-card">
        <header><h2>导出</h2></header>
        <button type="button" class="archive-primary" @click="emit('print')"><Printer :size="17" />导出归档 PDF</button>
        <p class="archive-note">在打印对话框中选择「另存为 PDF」，得到含签章的归档正式件。</p>
        <button type="button" class="archive-secondary" @click="exportWord"><FileDown :size="17" />导出 Word 文字版</button>
        <p class="archive-note">纯文字、保留下划线，适合二次编辑与摘录，不含手写签章。</p>
      </section>

      <button type="button" class="archive-back" @click="emit('back')"><ArrowLeft :size="16" />返回案件台账</button>
    </aside>
  </section>
</template>

<style scoped>
.record-archive { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; min-height: 0; height: 100%; color: var(--ink-700); font-size: var(--text-base); }

.archive-preview { min-height: 0; overflow: auto; padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface-muted); }
.archive-paper { width: 794px; margin: 0 auto; }
.archive-signatures { margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--paper-rule); }
.archive-signature { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; min-height: 40px; }
.archive-signature img { max-width: 200px; max-height: 70px; object-fit: contain; }
.archive-signatures > p { margin: 0; color: var(--paper-muted); font: var(--text-xs)/1.7 var(--font-sans); }

.archive-side { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; overflow: auto; }
.archive-card { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-5); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); }
.archive-card > header { display: flex; align-items: center; gap: var(--space-2); }
.archive-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 600; }
.archive-done { margin-left: auto; padding: 2px 10px; border-radius: var(--radius-pill); background: var(--success-100); color: var(--success-700); font-size: var(--text-xs); }

.archive-card dl { margin: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.archive-card dl > div { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); font-size: var(--text-sm); }
.archive-card dt { color: var(--ink-400); flex: 0 0 64px; }
.archive-card dd { margin: 0; color: var(--ink-700); text-align: right; overflow-wrap: anywhere; }
.archive-card dd.ok { color: var(--success-700); }

.archive-note { margin: 0; color: var(--ink-400); font-size: var(--text-xs); line-height: 1.7; }

.archive-primary { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 48px; border: 0; border-radius: var(--radius-md); background: var(--primary-600); color: var(--surface); font-size: var(--text-base); font-weight: 600; }
.archive-primary:hover { background: var(--primary-700); }
.archive-secondary { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 44px; border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--primary-600); font-size: var(--text-base); }

.archive-back { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 42px; border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-500); font-size: var(--text-base); }

@media (max-width: 1350px) { .record-archive { grid-template-columns: minmax(0, 1fr) 320px; gap: 14px; } }
@media print { .archive-side { display: none !important; } .record-archive { display: block; height: auto; } .archive-preview { padding: 0; background: var(--paper-bg); overflow: visible; } }
</style>
