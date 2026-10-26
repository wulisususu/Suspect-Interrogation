<script setup lang="ts">
import { computed, ref } from 'vue'
import { Minus, Plus, Printer, ShieldCheck } from '@lucide/vue'
import type { CaseSummary, DocumentSignerRole, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * ⑤ 签署归档
 *
 * 文书渲染与归档 PDF 一致，签章不再是一排按钮，而是文书末尾的三处热区：
 * 被询问人签名 / 指纹捺印 / 民警签名。签名齐备后在右侧确认归档并结案。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  signingState: DocumentSigningState | null
  busy: boolean
  archiving?: boolean
}>()

const emit = defineEmits<{
  print: []
  sign: [role: DocumentSignerRole]
  archive: []
}>()

const zoom = ref(70)
const fingerprintNotice = ref(false)
const copies = ref(2)
const paper = ref('A4 · 单面黑白')
const volumeNo = ref('')

const questions = computed(() => [...props.questions].sort((a, b) => a.sortOrder - b.sortOrder))
const wordCount = computed(() => questions.value.reduce((sum, item) => sum + (item.formalAnswerText?.trim().length || 0), 0))

function signature(role: DocumentSignerRole) {
  return props.signingState?.signatures.find((item) => item.signerRole === role)
}
const signedCount = computed(() => (['SUSPECT', 'OFFICER'] as DocumentSignerRole[]).filter((role) => signature(role)).length)
const signaturesReady = computed(() => signedCount.value === 2)
const printAllowed = computed(() => Boolean(props.signingState?.integrityValid && !props.busy))

const caseVolumeNo = computed(() => {
  const digits = (props.summary.id || '').replace(/\D/g, '').slice(-8) || '0000'
  return `2026-乙-${digits}-01`
})

function fact(key: string, fallback = '未填写') {
  const value = props.facts.find((item) => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : fallback
}
function time(value?: number | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未记录'
}
</script>

<template>
  <section class="record-signing-page">
    <div class="print-preview-column">
      <div class="print-preview-scroll" aria-label="询问笔录打印预览">
        <div class="print-preview-size" :style="{ width: `${794 * zoom / 100}px` }">
          <article class="signing-paper" :style="{ zoom: zoom / 100 }">
            <header><h2>询 问 笔 录</h2><p>询问次数：{{ fact('interrogation_round') }}</p></header>
            <section class="signing-paper-meta">
              <p>询问时间：{{ time(session.startedAt || summary.createdAt) }} 至 {{ time(session.endedAt) }}</p>
              <p>询问地点：{{ fact('interrogation_place') }}</p>
              <p>询问人：{{ summary.officerName || '未填写' }}　工作单位：{{ fact('officer_unit') }}</p>
              <p>记录人：{{ fact('recorder_name') }}　工作单位：{{ fact('recorder_unit') }}</p>
              <p>被询问人：{{ summary.suspectName || '未填写' }}　性别：{{ summary.gender || '未填写' }}　出生日期：{{ summary.birthDate || '未填写' }}</p>
              <p>证件类型：{{ fact('id_document_type', '身份证') }}　证件号码：{{ summary.idNumber || '未填写' }}</p>
              <p>联系方式：{{ fact('contact') }}　现住址：{{ summary.address || '未填写' }}</p>
              <p>案件编号：{{ summary.id }}</p>
            </section>
            <section class="signing-paper-body">
              <div v-for="question in questions" :key="question.id" class="print-qa">
                <p><b>问：</b>{{ question.text }}</p>
                <p><b>答：</b>{{ question.formalAnswerText || '（未获取）' }}</p>
              </div>
              <p v-if="!questions.length" class="print-empty">暂无正式问答内容，请返回定稿校验检查笔录。</p>
            </section>

            <footer class="paper-signatures">
              <div class="paper-hotspots record-no-print" aria-label="文末签章热区">
                <button
                  type="button"
                  class="hotspot"
                  :class="{ signed: signature('SUSPECT') }"
                  :disabled="!signingState || !!signature('SUSPECT') || busy"
                  @click="emit('sign', 'SUSPECT')"
                >
                  <span class="hotspot-title">被询问人签名</span>
                  <img v-if="signature('SUSPECT')" :src="signature('SUSPECT')!.imageDataUrl" alt="被询问人签名" />
                  <span v-else class="hotspot-hint">点击现场手写</span>
                </button>
                <button type="button" class="hotspot is-unavailable" title="本机未接入指纹采集器，捺印按纸质流程办理" @click="fingerprintNotice = true">
                  <span class="hotspot-title">指纹捺印</span>
                  <span class="hotspot-hint">未接入采集器</span>
                </button>
                <button
                  type="button"
                  class="hotspot"
                  :class="{ signed: signature('OFFICER') }"
                  :disabled="!signingState || !!signature('OFFICER') || busy"
                  @click="emit('sign', 'OFFICER')"
                >
                  <span class="hotspot-title">民警签名</span>
                  <img v-if="signature('OFFICER')" :src="signature('OFFICER')!.imageDataUrl" alt="民警签名" />
                  <span v-else class="hotspot-hint">点击调用预录入</span>
                </button>
              </div>
              <p v-if="signingState">冻结版本 {{ signingState.version }} · {{ signingState.documentHash }}</p>
              <p v-else>当前为定稿前文稿，尚未冻结</p>
            </footer>
          </article>
        </div>
      </div>
      <footer class="print-preview-controls record-no-print">
        <span>A4 竖向 · 210 × 297 mm</span>
        <button type="button" aria-label="缩小打印预览" :disabled="zoom <= 40" @click="zoom -= 10"><Minus :size="17" /></button>
        <span>{{ zoom }}%</span>
        <button type="button" aria-label="放大打印预览" :disabled="zoom >= 100" @click="zoom += 10"><Plus :size="17" /></button>
        <button type="button" :disabled="busy" @click="emit('print')"><Printer :size="16" />打印预览</button>
        <small>连续预览，打印时自动分页</small>
      </footer>
    </div>

    <aside class="signing-sidebar record-no-print">
      <section class="signing-card">
        <header><ShieldCheck :size="18" /><h2>笔录状态</h2></header>
        <dl>
          <div><dt>文稿</dt><dd :class="{ ok: signingState }">{{ signingState ? '已定稿 · 已冻结' : '待定稿' }}</dd></div>
          <div><dt>定稿时间</dt><dd>{{ signingState ? time(signingState.createdAt) : '未冻结' }}</dd></div>
          <div><dt>签名进度</dt><dd :class="{ ok: signaturesReady }">{{ signedCount }} / 2 处</dd></div>
          <div><dt>指纹捺印</dt><dd>未接入采集器</dd></div>
          <div><dt>完整性校验</dt><dd :class="{ ok: signingState?.integrityValid }">{{ signingState ? (signingState.integrityValid ? '通过' : '异常') : '未校验' }}</dd></div>
          <div><dt>文书字数</dt><dd>{{ wordCount }} 字 · {{ questions.length }} 题</dd></div>
        </dl>
        <p class="signing-note">签名完成后才能确认归档；归档后笔录转为只读。</p>
      </section>

      <section class="signing-card">
        <header><Printer :size="18" /><h2>打印与装卷</h2></header>
        <label class="signing-field"><span>打印机</span><input value="系统默认打印机" readonly /></label>
        <label class="signing-field"><span>份数</span><input v-model.number="copies" type="number" min="1" max="5" /><em>份</em></label>
        <label class="signing-field"><span>纸张</span><input v-model="paper" readonly /></label>
        <label class="signing-field"><span>卷号</span><input v-model="volumeNo" :placeholder="caseVolumeNo" /></label>
        <label class="signing-field"><span>归档人</span><input :value="summary.officerName || '未指定'" readonly /></label>

        <button type="button" class="signing-primary" :disabled="busy || archiving || !signaturesReady" @click="emit('archive')">
          {{ archiving ? '正在归档…' : signaturesReady ? '确认归档并结案' : '签名齐备后可归档' }}
        </button>
        <button type="button" class="signing-secondary" :disabled="!printAllowed" @click="emit('print')">
          <Printer :size="16" />{{ printAllowed ? '打印笔录' : '签名完成后可打印' }}
        </button>
        <p class="signing-note">{{ copies }} 份：1 份装卷、1 份交当事人。签章内嵌 PDF，打印后直接装卷。</p>
      </section>
    </aside>

    <div v-if="fingerprintNotice" class="signing-modal" role="dialog" aria-modal="true" aria-label="指纹捺印说明">
      <section class="signing-dialog">
        <header><h2>指纹捺印</h2><button type="button" @click="fingerprintNotice = false">关闭</button></header>
        <p>本机未接入指纹采集器，无法在屏幕上完成捺印采集。请按纸质流程在打印件上捺印后装卷。</p>
        <footer><button type="button" class="signing-primary" @click="fingerprintNotice = false">知道了</button></footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.record-signing-page { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 20px; min-height: 0; height: 100%; color: var(--ink-700); font-size: var(--text-base); }

.print-preview-column { min-height: 0; display: grid; grid-template-rows: minmax(0, 1fr) auto; overflow: hidden; border-radius: var(--radius-lg); background: var(--surface-muted); }
.print-preview-scroll { overflow: auto; min-width: 0; min-height: 0; padding: var(--space-5); }
.print-preview-size { margin: 0 auto; }

.signing-paper { width: 794px; min-height: 1123px; padding: 52px 48px 38px; box-sizing: border-box; background: var(--paper-bg); color: var(--paper-ink); font: var(--text-lg)/1.85 var(--font-serif); }
.signing-paper > header { text-align: center; margin-bottom: 26px; }
.signing-paper h2 { margin: 0; font-size: var(--text-3xl); font-weight: 600; letter-spacing: 4px; }
.signing-paper header p { margin: 4px 0; color: var(--paper-muted); font-size: var(--text-base); }
.signing-paper-meta { padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px solid var(--paper-rule); }
.signing-paper-meta p { margin: 0 0 6px; }
.signing-paper p { overflow-wrap: anywhere; }
.print-qa p { margin: 0 0 12px; white-space: pre-wrap; }
.print-qa b { font-weight: 600; }
.print-empty { color: var(--paper-muted); }

.paper-signatures { margin-top: 32px; }
.paper-signatures > p { padding-top: 16px; border-top: 1px solid var(--paper-rule); font: var(--text-xs)/1.7 var(--font-sans); color: var(--paper-muted); }

.paper-hotspots { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.hotspot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 92px;
  padding: 10px;
  border: 1px dashed var(--paper-hotspot-border);
  border-radius: var(--radius-sm);
  background: var(--paper-hotspot-bg);
  color: var(--primary-700);
  font-size: var(--text-sm);
}
.hotspot:hover:not(:disabled) { border-color: var(--primary-600); background: var(--primary-50); }
.hotspot.signed { border-style: solid; border-color: var(--success-600); background: var(--success-100); }
.hotspot:disabled { cursor: default; opacity: 0.75; }
.hotspot.is-unavailable { border-style: dotted; border-color: var(--line-300); background: var(--surface-sunken); color: var(--ink-400); }
.hotspot-title { font-weight: 600; }
.hotspot-hint { font-size: var(--text-xs); color: var(--ink-400); }
.hotspot img { max-width: 150px; max-height: 60px; object-fit: contain; }

.print-preview-controls { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 12px; padding: var(--space-3); font-size: var(--text-sm); color: var(--ink-400); }
.print-preview-controls button { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 12px; border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-sm); }

.signing-sidebar { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; overflow: auto; }
.signing-card { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-5); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); }
.signing-card > header { display: flex; align-items: center; gap: var(--space-2); }
.signing-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 600; }

.signing-card dl { margin: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.signing-card dl > div { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); font-size: var(--text-sm); }
.signing-card dt { color: var(--ink-400); }
.signing-card dd { margin: 0; padding: 3px 10px; border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-xs); }
.signing-card dd.ok { background: var(--success-100); color: var(--success-700); }

.signing-field { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-sm); }
.signing-field > span { flex: 0 0 56px; color: var(--ink-400); }
.signing-field > input { flex: 1 1 auto; min-width: 0; min-height: 34px; padding: 0 10px; border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--ink-700); font-size: var(--text-sm); }
.signing-field > input[readonly] { background: var(--surface-sunken); color: var(--ink-500); }
.signing-field > em { color: var(--ink-400); font-size: var(--text-xs); font-style: normal; }

.signing-primary { min-height: 48px; margin-top: var(--space-2); border: 0; border-radius: var(--radius-md); background: var(--primary-600); color: var(--surface); font-size: var(--text-base); font-weight: 600; }
.signing-primary:hover:not(:disabled) { background: var(--primary-700); }
.signing-primary:disabled { background: var(--surface-muted); color: var(--ink-300); cursor: not-allowed; }
.signing-secondary { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 42px; border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--primary-600); font-size: var(--text-base); }
.signing-secondary:disabled { color: var(--ink-300); border-color: var(--line-200); cursor: not-allowed; }

.signing-note { margin: 0; color: var(--ink-400); font-size: var(--text-xs); line-height: 1.7; }

.signing-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; background: rgba(16, 32, 56, 0.45); }
.signing-dialog { width: min(480px, 92vw); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.signing-dialog header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.signing-dialog h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.signing-dialog header button { min-height: 32px; padding: 0 12px; border: 1px solid var(--line-300); border-radius: var(--radius-pill); background: var(--surface); color: var(--ink-500); font-size: var(--text-sm); }
.signing-dialog p { margin: var(--space-4) 0; color: var(--ink-500); font-size: var(--text-base); line-height: 1.8; }
.signing-dialog footer { display: flex; justify-content: flex-end; }
.signing-dialog .signing-primary { min-width: 120px; margin: 0; }

@media (max-width: 1350px) { .record-signing-page { grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; } }
@media print { .record-no-print { display: none !important; } .record-signing-page { display: block; height: auto; } .print-preview-scroll { padding: 0; overflow: visible; } .print-preview-size { width: auto !important; } .signing-paper { zoom: 1 !important; width: auto; min-height: 0; padding: 0; } }
</style>
