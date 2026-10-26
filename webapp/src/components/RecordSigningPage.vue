<script setup lang="ts">
import { computed, ref } from 'vue'
import { Minus, Plus, Printer, ShieldCheck } from '@lucide/vue'
import type { CaseSummary, DocumentSignerRole, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { branding } from '../config/branding'
import { formatRecordTime, recordWordCount, volumeNumber } from '../utils/recordPaper'
import RecordPaper from './RecordPaper.vue'
import SignatureHotspotDialog from './SignatureHotspotDialog.vue'

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
  officers?: Array<{ officerId: string; officerName: string }>
}>()

const emit = defineEmits<{
  print: []
  sign: [role: DocumentSignerRole]
  archive: []
}>()

const zoom = ref(70)
const hotspotDialog = ref<'FINGERPRINT' | 'OFFICER' | null>(null)

function handwriteOfficer() {
  hotspotDialog.value = null
  emit('sign', 'OFFICER')
}

const wordCount = computed(() => recordWordCount(props.questions))

function signature(role: DocumentSignerRole) {
  return props.signingState?.signatures.find((item) => item.signerRole === role)
}
const signedCount = computed(() => (['SUSPECT', 'OFFICER'] as DocumentSignerRole[]).filter((role) => signature(role)).length)
const signaturesReady = computed(() => signedCount.value === 2)
const printAllowed = computed(() => Boolean(props.signingState?.integrityValid && !props.busy))

const caseVolumeNo = computed(() => volumeNumber(branding.volumePrefix, props.summary.id || ''))
</script>

<template>
  <section class="record-signing-page">
    <div class="print-preview-column">
      <div class="print-preview-scroll" aria-label="询问笔录打印预览">
        <div class="print-preview-size" :style="{ width: `${794 * zoom / 100}px` }">
          <RecordPaper class="signing-paper" :style="{ zoom: zoom / 100 }" :summary="summary" :facts="facts" :session="session" :questions="questions">
            <template #footer>
            <footer class="paper-signatures">
              <div class="paper-sign-row" aria-label="文末签章">
                <div class="paper-sign-cell">
                  <span class="paper-sign-label">被询问人签名：</span>
                  <img v-if="signature('SUSPECT')" :src="signature('SUSPECT')!.imageDataUrl" alt="被询问人签名" />
                  <button v-else type="button" class="hotspot record-no-print" :disabled="!signingState || busy" @click="emit('sign', 'SUSPECT')">
                    <span class="hotspot-title">被询问人签名 · 点击签名</span>
                    <span class="hotspot-hint">点击后弹出手写签名板（现场采集）</span>
                  </button>
                </div>
                <div class="paper-sign-cell">
                  <span class="paper-sign-label">指纹捺印：</span>
                  <button type="button" class="hotspot is-unavailable record-no-print" :disabled="!signingState" @click="hotspotDialog = 'FINGERPRINT'">
                    <span class="hotspot-title">指纹捺印 · 点击按压</span>
                    <span class="hotspot-hint">未接入采集器 · 按纸质流程捺印</span>
                  </button>
                </div>
                <div class="paper-sign-cell">
                  <span class="paper-sign-label">民警签名：</span>
                  <img v-if="signature('OFFICER')" :src="signature('OFFICER')!.imageDataUrl" alt="民警签名" />
                  <button v-else type="button" class="hotspot is-officer record-no-print" :disabled="!signingState || busy" @click="hotspotDialog = 'OFFICER'">
                    <span class="hotspot-title">民警签名 · 点击调用</span>
                    <span class="hotspot-hint">民警签名按警号预录入 · 一键调用</span>
                  </button>
                </div>
              </div>
              <p v-if="signingState">冻结版本 {{ signingState.version }} · {{ signingState.documentHash }}</p>
              <p v-else>当前为定稿前文稿，尚未冻结</p>
            </footer>
            </template>
          </RecordPaper>
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
          <div><dt>定稿时间</dt><dd>{{ signingState ? formatRecordTime(signingState.createdAt) : '未冻结' }}</dd></div>
          <div><dt>签名进度</dt><dd :class="{ ok: signaturesReady }">{{ signedCount }} / 3 处（文末热区完成）</dd></div>
          <div><dt>指纹捺印</dt><dd>未接入采集器</dd></div>
          <div><dt>完整性校验</dt><dd :class="{ ok: signingState?.integrityValid }">{{ signingState ? (signingState.integrityValid ? '通过' : '异常') : '未校验' }}</dd></div>
          <div><dt>文书字数</dt><dd>{{ wordCount }} 字 · {{ questions.length }} 题</dd></div>
        </dl>
        <div class="signing-row-actions">
          <button type="button" class="signing-secondary" disabled title="功能待接入">撤回定稿</button>
          <button type="button" class="signing-danger" disabled title="功能待接入">作废笔录</button>
        </div>
        <p class="signing-note">未签署前可撤回定稿（填原因留痕）· 作废须二次确认</p>
      </section>

      <section class="signing-card">
        <header><Printer :size="18" /><h2>打印与装卷</h2></header>
        <dl>
          <div><dt>打印机</dt><dd>系统默认打印机</dd></div>
          <div><dt>份数</dt><dd>2 份（1 份装卷 · 1 份交当事人）</dd></div>
          <div><dt>纸张</dt><dd>A4 · 单面黑白</dd></div>
          <div><dt>卷号</dt><dd>{{ caseVolumeNo }}</dd></div>
          <div><dt>归档人</dt><dd>{{ summary.officerName || '未指定' }}</dd></div>
          <div><dt>归档时间</dt><dd>签名捺印完成后自动登记</dd></div>
        </dl>

        <button type="button" class="signing-primary" :disabled="busy || archiving || !signaturesReady" @click="emit('archive')">
          {{ archiving ? '正在归档…' : signaturesReady ? '确认归档并结案' : '签名齐备后可归档' }}
        </button>
        <button type="button" class="signing-secondary" :disabled="!printAllowed" @click="emit('print')">
          <Printer :size="16" />{{ printAllowed ? '打印笔录' : '签名完成后可打印' }}
        </button>
        <p class="signing-note">打印件含已完成的签名；指纹按纸质流程在打印件上捺印后装卷。</p>
      </section>
    </aside>

    <SignatureHotspotDialog
      v-if="hotspotDialog"
      :role="hotspotDialog"
      :officers="officers ?? []"
      :busy="busy"
      @cancel="hotspotDialog = null"
      @handwrite="handwriteOfficer"
    />
  </section>
</template>

<style scoped>
.record-signing-page { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 20px; min-height: 0; height: 100%; color: var(--ink-700); font-size: var(--text-base); }

.print-preview-column { min-height: 0; display: grid; grid-template-rows: minmax(0, 1fr) auto; overflow: hidden; border-radius: var(--radius-lg); background: var(--surface-muted); }
.print-preview-scroll { overflow: auto; min-width: 0; min-height: 0; padding: var(--space-5); }
.print-preview-size { margin: 0 auto; }

.signing-paper { width: 794px; min-height: 1123px; }

.paper-signatures { margin-top: 32px; }
.paper-signatures > p { padding-top: 16px; border-top: 1px solid var(--paper-rule); font: var(--text-xs)/1.7 var(--font-sans); color: var(--paper-muted); }

.paper-sign-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.paper-sign-cell { display: flex; flex-direction: column; gap: 6px; min-height: 92px; }
.paper-sign-label { font: var(--text-sm)/1.5 var(--font-serif); }
.paper-sign-cell img { max-width: 100%; max-height: 72px; object-fit: contain; align-self: flex-start; }
.hotspot.is-officer { border-color: var(--success-600); background: var(--success-100); }
.signing-row-actions { display: flex; gap: var(--space-2); }
.signing-danger { flex: 1; min-height: 40px; border: 1px solid var(--danger-600); border-radius: var(--radius-md); background: var(--surface); color: var(--danger-700); font-size: var(--text-sm); font-weight: 600; }
.signing-row-actions .signing-secondary { flex: 1; }
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
@media print { .record-no-print { display: none !important; } .record-signing-page { display: block; height: auto; } .print-preview-scroll { padding: 0; overflow: visible; } .print-preview-size { width: auto !important; } }
</style>
