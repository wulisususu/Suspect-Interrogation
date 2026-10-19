<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Minus, Plus, Printer, ShieldCheck } from '@lucide/vue'
import type { CaseSummary, DocumentSignerRole, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

const props = defineProps<{
  summary: CaseSummary; facts: FactItem[]; session: SessionState; questions: FormalQuestion[]
  signingState: DocumentSigningState | null; busy: boolean; checks: boolean[]; blockReason: string
}>()
defineEmits<{ check: [index: number, checked: boolean]; freeze: []; print: []; sign: [role: DocumentSignerRole]; review: [] }>()
const zoom = ref(70)
const questions = computed(() => [...props.questions].sort((a, b) => a.sortOrder - b.sortOrder))
const checkLabels = [
  '姓名、证件号码已与证件原件核对',
  '询问时间、地点及询问人、记录人信息已核对',
  '说话人身份、问答归属与文字已人工复核',
  '录音归档、转写与问答处理状态已检查',
  '已查看打印预览并核对版面',
]
const remaining = computed(() => checkLabels.filter((_, index) => !props.checks[index]).length)
const signatureRoles: DocumentSignerRole[] = ['SUSPECT', 'OFFICER']
function signature(role: DocumentSignerRole) { return props.signingState?.signatures.find(item => item.signerRole === role) }
function fact(key: string, fallback = '未填写') {
  const value = props.facts.find(item => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : fallback
}
function time(value?: number | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未记录'
}
const printAllowed = computed(() => Boolean(props.signingState?.integrityValid && !props.busy))
</script>

<template>
  <section class="record-signing-page">
    <div class="print-preview-column">
      <div class="print-preview-scroll" aria-label="询问笔录打印预览"><div class="print-preview-size" :style="{ width: `${794 * zoom / 100}px` }"><article class="signing-paper" :style="{ zoom: zoom / 100 }">
        <header><h2>询 问 笔 录</h2><p>询问次数：{{ fact('interrogation_round') }}</p></header>
        <section class="signing-paper-meta"><p>询问时间：{{ time(session.startedAt || summary.createdAt) }} 至 {{ time(session.endedAt) }}</p><p>询问地点：{{ fact('interrogation_place') }}</p><p>询问人：{{ summary.officerName || '未填写' }}　工作单位：{{ fact('officer_unit') }}</p><p>记录人：{{ fact('recorder_name') }}　工作单位：{{ fact('recorder_unit') }}</p><p>被询问人：{{ summary.suspectName || '未填写' }}　性别：{{ summary.gender || '未填写' }}　出生日期：{{ summary.birthDate || '未填写' }}</p><p>证件类型：{{ fact('id_document_type', '身份证') }}　证件号码：{{ summary.idNumber || '未填写' }}</p><p>联系方式：{{ fact('contact') }}</p><p>户籍所在地：{{ fact('household_registration') }}</p><p>现住址：{{ summary.address || '未填写' }}</p><p>案件编号：{{ summary.id }}</p></section>
        <section class="signing-paper-body"><div v-for="question in questions" :key="question.id" class="print-qa"><p><b>问：</b>{{ question.text }}</p><p><b>答：</b>{{ question.formalAnswerText || '（未填写）' }}</p></div><p v-if="!questions.length" class="print-empty">暂无正式问答内容，请返回复核检查笔录。</p></section>
        <footer class="paper-signatures"><div v-for="role in signatureRoles" :key="role"><span>{{ role === 'SUSPECT' ? '被询问人签名：' : '询问人签名：' }}</span><img v-if="signature(role)" :src="signature(role)!.imageDataUrl" :alt="role === 'SUSPECT' ? '被询问人签名' : '询问人签名'" /><span v-else>________________</span><small v-if="signature(role)">{{ time(signature(role)!.signedAt) }}</small></div><p v-if="signingState">冻结版本 {{ signingState.version }} · {{ signingState.documentHash }}</p><p v-else>当前为复核稿，尚未冻结</p></footer>
      </article></div></div>
      <footer class="print-preview-controls record-no-print"><span>A4 竖向 · 210 × 297 mm</span><button aria-label="缩小打印预览" :disabled="zoom <= 40" @click="zoom -= 10"><Minus :size="17" /></button><span>{{ zoom }}%</span><button aria-label="放大打印预览" :disabled="zoom >= 100" @click="zoom += 10"><Plus :size="17" /></button><button :disabled="busy" @click="$emit('print')"><Printer :size="16" />打印预览</button><small>连续预览，打印时自动分页</small></footer>
    </div>
    <aside class="signing-sidebar record-no-print">
      <section class="freeze-checklist"><header><ShieldCheck :size="20" /><h2>冻结确认 · 打印前核对</h2></header><p>{{ signingState ? '当前版本已冻结，只能打印与签名；签名状态以服务端记录为准。' : '逐项核对后才能冻结；冻结后笔录不能继续编辑。' }}</p>
        <label v-for="(label, index) in checkLabels" v-show="!signingState" :key="label" :class="{ checked: checks[index] }"><input type="checkbox" :checked="checks[index]" :disabled="busy || !!signingState" @change="$emit('check', index, ($event.target as HTMLInputElement).checked)" /><span>{{ label }}</span></label>
        <button class="primary freeze-button" :disabled="busy || !!blockReason" @click="$emit('freeze')">{{ signingState ? '笔录已冻结' : busy ? '处理中…' : remaining ? `确认冻结 · 还有 ${remaining} 项未核对` : '确认冻结笔录' }}</button><p v-if="blockReason && !signingState" class="freeze-block-reason" role="status">{{ blockReason }}</p><p v-if="signingState" class="frozen-notice"><Check :size="16" />冻结版本 {{ signingState.version }} · {{ signingState.integrityValid ? '完整性校验通过' : '完整性校验异常，请检查' }}</p><button v-if="!signingState" class="back-review" :disabled="busy" @click="$emit('review')">返回复核处理</button>
      </section>
      <section class="signing-progress"><h2>冻结、打印与签署</h2><dl><div><dt>冻结笔录</dt><dd :class="{ complete: signingState }">{{ signingState ? '已冻结' : '待冻结' }}</dd></div><div><dt>正式笔录打印</dt><dd>需在打印机确认</dd></div><div v-for="role in signatureRoles" :key="role"><dt>{{ role === 'SUSPECT' ? '被询问人电子签名' : '民警电子签名' }}</dt><dd :class="{ complete: signature(role) }">{{ signature(role) ? '已签名' : '待签名' }}</dd></div></dl><button class="primary print-button" :disabled="!printAllowed" @click="$emit('print')"><Printer :size="18" />{{ signingState ? '打印正式笔录' : '打印正式笔录 · 需先完成冻结' }}</button><div class="signature-buttons"><button v-for="role in signatureRoles" :key="role" :disabled="!printAllowed || !!signature(role) || signingState?.status === 'LOCKED'" @click="$emit('sign', role)">{{ role === 'SUSPECT' ? '被询问人签名' : '民警签名' }}</button></div><p>打印结果请在打印机核实。纸质签字、捺印按现场流程办理；电子签名使用已有签名功能。</p></section>
    </aside>
  </section>
</template>

<style scoped>
.record-signing-page { display:grid; grid-template-columns:minmax(0,1fr) 420px; gap:26px; min-height:0; height:100%; color:#34435b; font-size:15px; }.print-preview-column { min-height:0; display:grid; grid-template-rows:minmax(0,1fr) auto; overflow:hidden; border-radius:13px; background:#e6ebf3; }.print-preview-scroll { overflow:auto; min-width:0; min-height:0; padding:22px; }.print-preview-size { margin:0 auto; }.signing-paper { width:794px; min-height:1123px; padding:52px 48px 38px; box-sizing:border-box; background:#fff; color:#242b35; font:17px/1.85 "FangSong","STFangsong","SimSun",serif; }.signing-paper > header { text-align:center; margin-bottom:26px; }.signing-paper h2 { margin:0; font-size:30px; font-weight:600; letter-spacing:4px; }.signing-paper header p { margin:4px 0; color:#8c97a6; font-size:14px; }.signing-paper-meta { padding-bottom:14px; margin-bottom:16px; border-bottom:1px solid #dce2eb; }.signing-paper-meta p { margin:0 0 6px; }.signing-paper p { overflow-wrap:anywhere; }.print-qa p { margin:0 0 12px; white-space:pre-wrap; }.print-qa b { font-weight:600; }.paper-signatures { margin-top:30px; }.paper-signatures > div { display:flex; align-items:center; flex-wrap:wrap; gap:14px; margin:16px 0; min-height:42px; }.paper-signatures img { max-width:200px; max-height:70px; object-fit:contain; }.paper-signatures small { color:#8590a1; font-size:12px; }.paper-signatures > p { padding-top:16px; border-top:1px solid #dce2eb; font:12px/1.7 system-ui,sans-serif; color:#95a0af; }
.print-preview-controls { display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:12px; padding:16px; font-size:13px; color:#7d8ca3; }.print-preview-controls small { font-size:12px; }.print-preview-controls button { display:inline-flex; align-items:center; justify-content:center; gap:7px; min-height:38px; padding:0 12px; }
button,input { font:inherit; }button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:46px; padding:0 18px; border:1px solid #d2ddea; border-radius:9px; color:#205293; background:#fff; cursor:pointer; font-size:15px; }button.primary { color:#fff; background:#205293; border-color:#205293; }button:disabled { background:#e8edf5; border-color:#e8edf5; color:#94a2b7; cursor:not-allowed; }button:focus-visible,input:focus-visible { outline:3px solid #87afe1; outline-offset:3px; }
.signing-sidebar { display:flex; flex-direction:column; gap:18px; min-height:0; overflow:auto; }.signing-sidebar > section { padding:24px; border-radius:13px; background:#fff; }.signing-sidebar h2 { margin:0; font-size:18px; color:#26364c; }.freeze-checklist > header { display:flex; gap:9px; align-items:center; }.signing-sidebar p { margin:14px 0 0; color:#8b99ae; font-size:13px; line-height:1.8; }.freeze-checklist label { display:flex; align-items:center; gap:14px; line-height:1.65; margin:18px 0; cursor:pointer; font-size:14px; }.freeze-checklist label.checked { color:#327e51; }.freeze-checklist input { width:24px; height:24px; flex:0 0 24px; accent-color:#205293; }.freeze-button { width:100%; min-height:54px; margin-top:4px; }.freeze-block-reason { color:#a57325 !important; }.frozen-notice { display:flex; align-items:center; gap:7px; color:#2c8150 !important; }.back-review { width:100%; margin-top:14px; }.signing-progress dl { margin:18px 0; }.signing-progress dl > div { display:flex; gap:12px; justify-content:space-between; align-items:center; margin:12px 0; font-size:14px; }.signing-progress dt { color:#7b8aa2; }.signing-progress dd { margin:0; background:#f0f3f8; color:#8190a6; padding:5px 10px; border-radius:20px; font-size:12px; }.signing-progress dd.complete { color:#2a8350; background:#e8f6ed; }.print-button { width:100%; min-height:52px; }.signature-buttons { display:flex; gap:10px; margin-top:12px; }.signature-buttons button { flex:1; padding:0 12px; font-size:14px; }
@media(max-width:1350px) { .record-signing-page { grid-template-columns:minmax(0,1fr) 360px; gap:18px; }.signing-sidebar > section { padding:20px; }.print-preview-scroll { padding:16px; } }
@media(max-width:1000px) { .record-signing-page { display:block; height:auto; }.print-preview-column { height:650px; }.signing-sidebar { overflow:visible; margin-top:18px; display:grid; grid-template-columns:1fr 1fr; }.print-preview-scroll { max-width:100%; } }
@media(max-width:700px) { .signing-sidebar { grid-template-columns:1fr; }.print-preview-column { height:550px; }.print-preview-controls { gap:8px; } }
@media print { .record-signing-page { display:block!important; height:auto!important; }.print-preview-column,.print-preview-scroll { height:auto!important; display:block!important; overflow:visible!important; padding:0!important; background:#fff; }.print-preview-size { width:auto!important; margin:0; }.signing-paper { zoom:1!important; width:auto; min-height:0; margin:0; padding:0; font-size:12pt; box-shadow:none; }.signing-paper h2 { font-size:22pt; }.print-qa,.paper-signatures > div { break-inside:avoid; } }
</style>
