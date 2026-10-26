<script lang="ts">
import { voiceprintStartGuard } from './VoiceprintPreparationPanel.vue'
import type { CaseSummary, VoiceprintEnrollmentState, VoiceprintReadiness } from '../types/interrogation'
import type { RuntimeCapabilities } from '../runtime/types'

export function preparationStartGuard(summary: CaseSummary, readiness: VoiceprintReadiness, capabilities: RuntimeCapabilities | null, enrollmentState: VoiceprintEnrollmentState) {
  const identityRecorded = Boolean(summary.suspectName && summary.suspectName !== '待录入' && summary.idNumber && summary.identitySource)
  const deviceReady = capabilities?.microphone.state === 'AVAILABLE' && capabilities?.asr.state === 'AVAILABLE'
  const voiceReady = !voiceprintStartGuard(readiness).disabled && !readiness.simulated
  const enrollmentBusy = ['RECORDING', 'PROCESSING'].includes(enrollmentState.phase)
  const missing = [!identityRecorded && '身份信息', !voiceReady && '嫌疑人声纹注册', !deviceReady && '设备自检'].filter((value): value is string => Boolean(value))
  return {
    identityRecorded, deviceReady, voiceReady, missing, enrollmentBusy,
    disabled: Boolean(missing.length || enrollmentBusy),
    reason: missing.length ? '完成以下项目后解锁：' + missing.join('、') : enrollmentBusy ? '请先完成当前声纹采集' : '三项准备已就绪，可以开始审讯',
  }
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, Check, ClipboardCheck, Mic, RefreshCw, ShieldCheck } from '@lucide/vue'
import { voiceprintEnrollmentProgress, voiceprintDegradationNotice } from './VoiceprintPreparationPanel.vue'
import type { FactItem, SessionStatus } from '../types/interrogation'

const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  readiness: VoiceprintReadiness
  enrollmentState: VoiceprintEnrollmentState
  capabilities: RuntimeCapabilities | null
  sessionStatus: SessionStatus
  recorderName: string
  busy?: boolean
  deviceError?: string
}>()
defineEmits<{ profile: []; voiceprint: []; refresh: []; start: []; interrogation: [] }>()

function fact(key: string) {
  const value = props.facts.find((item) => item.key === key)?.value
  return value && value !== '未录入' ? value : '未填写'
}
const guard = computed(() => preparationStartGuard(props.summary, props.readiness, props.capabilities, props.enrollmentState))
const identityRecorded = computed(() => guard.value.identityRecorded)
const identitySource = computed(() => ({ ID_CARD_READER: '居民身份证读取', MANUAL: '人工录入', OCR: '证件图像录入' })[props.summary.identitySource || ''] || '未标记')
const maskedId = computed(() => {
  const value = props.summary.idNumber || ''
  return value.length > 8 ? value.slice(0, 4) + '*'.repeat(value.length - 8) + value.slice(-4) : value || '未填写'
})
const deviceReady = computed(() => guard.value.deviceReady)
const voiceReady = computed(() => guard.value.voiceReady)
const progress = computed(() => voiceprintEnrollmentProgress(props.enrollmentState))
const startDisabled = computed(() => Boolean(props.busy || guard.value.disabled))
const degradation = computed(() => voiceprintDegradationNotice(props.readiness))
</script>

<template>
  <div class="preparation-page">
    <section class="preparation-main">
      <header class="preparation-heading"><h1>建档 · 核对身份与设备</h1><p>{{ summary.id }} · {{ summary.suspectName || '待录入' }} · 主审民警 {{ summary.officerName || '未指定' }} · 记录员 {{ recorderName }}</p></header>
      <section class="preparation-checklist" aria-label="开始前检查">
        <header><h2>开始前检查</h2><p>完成身份信息、声纹注册和设备检查后，即可开始审讯</p></header>
        <article class="check-row" :class="{ complete: identityRecorded }">
          <span class="check-icon"><Check v-if="identityRecorded" :size="28" /><ShieldCheck v-else :size="28" /></span>
          <div class="check-content"><h3>身份信息 · {{ identityRecorded ? '已录入' : '待补充' }}</h3><p>{{ summary.suspectName || '姓名待录入' }} · {{ summary.gender || '性别未填写' }} · {{ summary.age ? summary.age + ' 岁' : '年龄未填写' }} · {{ identitySource }}</p><small>请对照证件原件核对本人信息</small></div>
          <button class="check-link" @click="$emit('profile')">{{ identityRecorded ? '核对 / 编辑' : '补充身份信息' }}<ArrowRight :size="16" /></button>
        </article>
        <article class="check-row voice-check" :class="{ complete: voiceReady }">
          <span class="check-icon"><Check v-if="voiceReady" :size="28" /><Mic v-else :size="28" /></span>
          <div class="check-content"><h3>嫌疑人声纹注册 · {{ voiceReady ? '已完成' : enrollmentState.phase === 'RECORDING' ? '进行中' : enrollmentState.phase === 'PROCESSING' ? '处理中' : '待注册' }}</h3><div class="voice-progress" role="progressbar" aria-label="嫌疑人有效语音采集进度" :aria-valuenow="voiceReady ? 100 : progress.percent" :aria-valuemin="0" :aria-valuemax="100"><span :style="{ width: (voiceReady ? 100 : progress.percent) + '%' }"></span></div><p>{{ voiceReady ? '声纹已就绪，可用于本次询问的说话人识别' : '有效语音 ' + progress.usableSeconds + ' 秒 / ' + progress.targetSeconds + ' 秒 · 请引导被询问人自然、连续说话' }}</p><small>采集在独立页面进行，进度同步至检查单</small></div>
          <button class="capture-link" @click="$emit('voiceprint')">{{ voiceReady ? '查看声纹' : '进入采集页' }}<ArrowRight :size="16" /></button>
        </article>
        <article class="check-row" :class="{ complete: deviceReady }">
          <span class="check-icon"><Check v-if="deviceReady" :size="28" /><ClipboardCheck v-else :size="28" /></span>
          <div class="check-content"><h3>设备自检 · {{ deviceReady ? '已通过' : capabilities ? '待就绪' : '检查中' }}</h3><p>一体机麦克风 · {{ capabilities?.microphone.state === 'AVAILABLE' ? '正常' : capabilities?.microphone.reason || '未就绪' }}<br v-if="!deviceReady" /><span v-else>　</span>语音识别服务 · {{ capabilities?.asr.state === 'AVAILABLE' ? '正常' : capabilities?.asr.reason || '未就绪' }}</p><small>人工录入身份时，无需连接读卡器</small></div>
          <button class="check-link" :disabled="busy" @click="$emit('refresh')"><RefreshCw :size="15" />重新自检</button>
        </article>
        <p v-if="deviceError" class="preparation-warning" role="alert">{{ deviceError }}</p>
        <p v-if="degradation" class="preparation-warning">{{ degradation }}</p>
        <footer class="preparation-footer">
          <template v-if="sessionStatus === 'READY'"><p>{{ guard.reason }}</p><button class="start-interrogation" :disabled="startDisabled" @click="$emit('start')">开始审讯<ArrowRight :size="19" /></button></template>
          <template v-else><p>本案{{ sessionStatus === 'COMPLETED' ? '已结束审讯，可进入工作台复核笔录' : '已有审讯会话，请进入工作台继续处理' }}</p><button class="start-interrogation" @click="$emit('interrogation')">进入审讯工作台<ArrowRight :size="19" /></button></template>
        </footer>
      </section>
    </section>
    <aside class="preparation-sidebar">
      <section class="preparation-card"><h2>身份信息</h2><dl><div><dt>姓名</dt><dd>{{ summary.suspectName || '未填写' }}</dd></div><div><dt>证件号码</dt><dd>{{ maskedId }}</dd></div><div><dt>案件类型</dt><dd>{{ fact('case_type') }}</dd></div><div><dt>询问地点</dt><dd>{{ fact('interrogation_place') }}</dd></div><div><dt>询问人 · 记录人</dt><dd>{{ summary.officerName || '未指定' }} · {{ recorderName }}</dd></div><div><dt>是否人大代表</dt><dd>{{ fact('peoples_representative') }}</dd></div><div><dt>身份来源</dt><dd>{{ identitySource }}</dd></div><div><dt>询问次数</dt><dd>{{ fact('interrogation_round') === '未填写' ? '未填写' : '第 ' + fact('interrogation_round') + ' 次' }}</dd></div></dl><button class="check-link" @click="$emit('profile')">查看完整身份信息<ArrowRight :size="15" /></button></section>
      <section class="preparation-card"><h2>声纹采集与绑定</h2><ul><li>静音和长时间停顿不计入有效时长</li><li>避免多人同时说话，保持正常音量</li><li>声纹用于区分说话人</li></ul><div class="officer-binding"><strong>民警声纹绑定（可选）</strong><span :class="{ bound: readiness.interrogatorReady }">主审民警 · {{ readiness.interrogatorReady ? '已绑定' : '未绑定' }}</span><span :class="{ bound: readiness.recorderReady }">记录民警 · {{ readiness.recorderReady ? '已绑定' : '未绑定' }}</span><button class="check-link" @click="$emit('voiceprint')">管理绑定<ArrowRight :size="15" /></button></div></section>
    </aside>
  </div>
</template>

<style scoped>
.preparation-page { display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 26px; min-height: 100%; padding: 28px 32px 32px; max-width: 1920px; margin: 0 auto; color: var(--primary-700); font-size: var(--text-md); }
.preparation-main { display: flex; flex-direction: column; min-width: 0; }
.preparation-heading h1 { margin: 0 0 12px; color: var(--navy-900); font-size: var(--text-2xl); } .preparation-heading p { margin: 0; color: var(--ink-400); }
.preparation-checklist { display: flex; flex: 1; flex-direction: column; padding: 28px; background: var(--surface); border-radius: 13px; min-height: 580px; }
h2 { margin: 0 0 8px; font-size: var(--text-xl); color: var(--primary-700); } .preparation-checklist header p { margin: 0 0 22px; color: var(--ink-400); font-size: var(--text-base); }
.check-row { display: flex; align-items: center; gap: 20px; padding: 24px 0; border-bottom: 1px solid var(--primary-100); }
.check-row:last-of-type { border-bottom: 0; }
.check-icon { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 50%; flex: 0 0 52px; color: var(--warning-600); background: var(--warning-100); }
.complete .check-icon { color: var(--success-700); background: var(--success-100); }
.check-content { min-width: 0; flex: 1; } h3 { margin: 0 0 8px; font-size: var(--text-lg); color: var(--warning-600); } .complete h3 { color: var(--success-700); }
.check-content p { margin: 6px 0; font-size: var(--text-base); color: var(--ink-400); line-height: 1.7; overflow-wrap: anywhere; } .check-content small { font-size: var(--text-sm); color: var(--ink-400); }
button { font: inherit; } .check-link { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 0; padding: 6px 0; background: transparent; color: var(--primary-600); font-size: var(--text-base); white-space: nowrap; }
.capture-link { display: flex; align-items: center; gap: 8px; border: 0; padding: 13px 17px; color: var(--surface); background: var(--warning-600); border-radius: 9px; font-size: var(--text-md); white-space: nowrap; }
.voice-check.complete .capture-link { background: var(--primary-600); }
.voice-progress { height: 10px; overflow: hidden; border-radius: 20px; background: var(--warning-100); margin: 8px 0; } .voice-progress span { display: block; height: 100%; background: var(--warning-700); border-radius: inherit; transition: width .2s; } .complete .voice-progress { background: var(--success-100); } .complete .voice-progress span { background: var(--success-600); }
.preparation-footer { margin-top: 24px; } .preparation-footer p { background: var(--primary-100); color: var(--primary-600); padding: 14px; border-radius: 9px; text-align: center; margin: 0; font-size: var(--text-base); }
.start-interrogation { width: 100%; min-height: 54px; display: flex; align-items: center; justify-content: center; gap: 12px; border: 0; border-radius: 9px; background: var(--primary-600); color: var(--surface); font-weight: 700; font-size: var(--text-lg); } .start-interrogation:disabled { background: var(--line-300); color: var(--surface); opacity: 1; }
.preparation-sidebar { display: flex; flex-direction: column; gap: 20px; } .preparation-card { padding: 22px; border-radius: 13px; background: var(--surface); } .preparation-card h2 { font-size: var(--text-lg); margin-bottom: 15px; }
dl { margin: 0 0 10px; } dl > div { display: grid; grid-template-columns: 95px minmax(0,1fr); gap: 10px; padding: 7px 0; font-size: var(--text-sm); } dt { color: var(--ink-400); } dd { margin: 0; text-align: right; overflow-wrap: anywhere; color: var(--primary-700); }
.preparation-card ul,.preparation-card ol { padding-left: 18px; margin: 0; color: var(--ink-400); font-size: var(--text-sm); line-height: 2.2; }
.officer-binding { display: flex; flex-wrap: wrap; gap: 9px; padding-top: 14px; border-top: 1px solid var(--primary-100); margin-top: 12px; } .officer-binding strong { width: 100%; font-size: var(--text-sm); } .officer-binding > span { background: var(--surface-sunken); padding: 7px 9px; border-radius: 20px; color: var(--ink-400); font-size: var(--text-xs); } .officer-binding > span.bound { background: var(--success-100); color: var(--success-700); }
.preparation-warning { padding: 12px; background: var(--warning-100); color: var(--warning-600); border-radius: 8px; font-size: var(--text-base); }
@media(max-width: 1480px) { .preparation-page { padding: 22px 24px; grid-template-columns: minmax(0,1fr) 260px; gap: 18px; } .preparation-checklist { padding: 24px; } .check-row { gap: 14px; } .preparation-card { padding: 18px; } }
@media(max-width: 1150px) { .preparation-page { grid-template-columns: 1fr; } .preparation-sidebar { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; } }
@media(max-height: 800px) { .preparation-checklist { min-height: 500px; } .check-row { padding: 19px 0; } }
@media(max-width: 720px) { .preparation-page { padding: 16px; } .preparation-sidebar { grid-template-columns: 1fr; } .check-row { flex-wrap: wrap; } .check-row button { margin-left: 66px; } }
</style>
