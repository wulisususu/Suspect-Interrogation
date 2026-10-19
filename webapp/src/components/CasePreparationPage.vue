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
import { ArrowRight, Check, ChevronRight, ClipboardCheck, Mic, RefreshCw, ShieldCheck } from '@lucide/vue'
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
const steps = ['准备', '审讯', '复核', '签署']
const currentStep = computed(() => {
  const workflow = props.summary.workflowState
  if (['FROZEN', 'SIGNED', 'REPORT_GENERATED'].includes(workflow || '')) return 3
  if (workflow === 'SUMMARY' || props.sessionStatus === 'COMPLETED') return 2
  if (['RUNNING', 'PAUSED'].includes(props.sessionStatus)) return 1
  return 0
})
</script>

<template>
  <div class="preparation-page">
    <section class="preparation-main">
      <header class="preparation-heading"><h1>案件工作台</h1><p>{{ summary.id }} · {{ summary.suspectName || '待录入' }} · 主审民警 {{ summary.officerName || '未指定' }} · 记录员 {{ recorderName }}</p></header>
      <nav class="preparation-steps" aria-label="询问流程阶段"><template v-for="(step, index) in steps" :key="step"><ChevronRight v-if="index" :size="18" aria-hidden="true" /><span :class="{ current: index === currentStep }" :aria-current="index === currentStep ? 'step' : undefined">{{ index + 1 }} {{ step }}{{ index === currentStep ? ' · 当前' : '' }}</span></template></nav>
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
      <section class="preparation-card preparation-guide"><h2>询问流程指引</h2><ol><li>准备 — 身份信息与声纹采集</li><li>审讯 — 实时转写并预写笔录</li><li>复核 — 逐段确认转写内容</li><li>签署 — 冻结后打印与手写签名</li></ol><p>冻结签署后笔录锁定，不可再修改</p></section>
    </aside>
  </div>
</template>

<style scoped>
.preparation-page { display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 26px; min-height: 100%; padding: 28px 32px 32px; max-width: 1920px; margin: 0 auto; color: #243550; font-size: 15px; }
.preparation-main { display: flex; flex-direction: column; min-width: 0; }
.preparation-heading h1 { margin: 0 0 12px; color: #1c2e49; font-size: 26px; } .preparation-heading p { margin: 0; color: #748196; }
.preparation-steps { display: flex; align-items: center; gap: 12px; margin: 18px 0 24px; color: #a5afbd; }
.preparation-steps span { padding: 12px 18px; border-radius: 9px; background: #fff; color: #748196; font-weight: 600; }
.preparation-steps .current { color: #fff; background: #205293; }
.preparation-checklist { display: flex; flex: 1; flex-direction: column; padding: 28px; background: #fff; border-radius: 13px; min-height: 580px; }
h2 { margin: 0 0 8px; font-size: 18px; color: #26364c; } .preparation-checklist header p { margin: 0 0 22px; color: #91a0b5; font-size: 14px; }
.check-row { display: flex; align-items: center; gap: 20px; padding: 24px 0; border-bottom: 1px solid #edf1f7; }
.check-row:last-of-type { border-bottom: 0; }
.check-icon { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 50%; flex: 0 0 52px; color: #ad761e; background: #fff5e5; }
.complete .check-icon { color: #238348; background: #eaf7ef; }
.check-content { min-width: 0; flex: 1; } h3 { margin: 0 0 8px; font-size: 17px; color: #ad761e; } .complete h3 { color: #238348; }
.check-content p { margin: 6px 0; font-size: 14px; color: #708199; line-height: 1.7; overflow-wrap: anywhere; } .check-content small { font-size: 13px; color: #8b9ab0; }
button { font: inherit; } .check-link { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 0; padding: 6px 0; background: transparent; color: #205293; font-size: 14px; white-space: nowrap; }
.capture-link { display: flex; align-items: center; gap: 8px; border: 0; padding: 13px 17px; color: #fff; background: #ad741b; border-radius: 9px; font-size: 15px; white-space: nowrap; }
.voice-check.complete .capture-link { background: #205293; }
.voice-progress { height: 10px; overflow: hidden; border-radius: 20px; background: #f0e8d7; margin: 8px 0; } .voice-progress span { display: block; height: 100%; background: #e6a238; border-radius: inherit; transition: width .2s; } .complete .voice-progress { background: #e9f6ef; } .complete .voice-progress span { background: #41aa73; }
.preparation-footer { margin-top: 24px; } .preparation-footer p { background: #eaf1fb; color: #3c6596; padding: 14px; border-radius: 9px; text-align: center; margin: 0; font-size: 14px; }
.start-interrogation { width: 100%; min-height: 54px; display: flex; align-items: center; justify-content: center; gap: 12px; border: 0; border-radius: 9px; background: #205293; color: #fff; font-weight: 700; font-size: 16px; } .start-interrogation:disabled { background: #c6d2e3; color: #fff; opacity: 1; }
.preparation-sidebar { display: flex; flex-direction: column; gap: 20px; } .preparation-card { padding: 22px; border-radius: 13px; background: #fff; } .preparation-card h2 { font-size: 16px; margin-bottom: 15px; }
dl { margin: 0 0 10px; } dl > div { display: grid; grid-template-columns: 95px minmax(0,1fr); gap: 10px; padding: 7px 0; font-size: 13px; } dt { color: #91a0b5; } dd { margin: 0; text-align: right; overflow-wrap: anywhere; color: #34435b; }
.preparation-card ul,.preparation-card ol { padding-left: 18px; margin: 0; color: #7a89a0; font-size: 13px; line-height: 2.2; }
.officer-binding { display: flex; flex-wrap: wrap; gap: 9px; padding-top: 14px; border-top: 1px solid #edf1f7; margin-top: 12px; } .officer-binding strong { width: 100%; font-size: 13px; } .officer-binding > span { background: #f2f5f9; padding: 7px 9px; border-radius: 20px; color: #7a89a0; font-size: 12px; } .officer-binding > span.bound { background: #e8f6ed; color: #27824e; }
.preparation-guide { flex: 1; display: flex; flex-direction: column; } .preparation-guide p { margin: auto 0 0; padding-top: 24px; color: #91a0b5; font-size: 12px; }
.preparation-warning { padding: 12px; background: #fff5e5; color: #a16b20; border-radius: 8px; font-size: 14px; }
@media(max-width: 1480px) { .preparation-page { padding: 22px 24px; grid-template-columns: minmax(0,1fr) 260px; gap: 18px; } .preparation-checklist { padding: 24px; } .check-row { gap: 14px; } .preparation-card { padding: 18px; } }
@media(max-width: 1150px) { .preparation-page { grid-template-columns: 1fr; } .preparation-sidebar { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; } }
@media(max-height: 800px) { .preparation-checklist { min-height: 500px; } .check-row { padding: 19px 0; } }
@media(max-width: 720px) { .preparation-page { padding: 16px; } .preparation-sidebar { grid-template-columns: 1fr; } .preparation-steps { gap: 5px; } .preparation-steps span { padding: 10px; } .check-row { flex-wrap: wrap; } .check-row button { margin-left: 66px; } }
</style>
