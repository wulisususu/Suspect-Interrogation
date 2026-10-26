<script lang="ts">
import type { TemporaryAsrSpeaker, VoiceprintReadiness as VoiceprintReadinessModel, VoiceRecognitionMode } from '../types/interrogation'

export function voiceprintEnrollmentProgress(value: {
  capturedDurationMs?: number | null
  targetDurationMs?: number | null
  usableSpeechMs?: number | null
  requiredUsableSpeechMs?: number | null
}) {
  const targetDurationMs = Math.max(1, Number(value.requiredUsableSpeechMs ?? value.targetDurationMs ?? 60000))
  const usableDurationMs = Math.max(0, Math.min(Number(value.usableSpeechMs ?? value.capturedDurationMs ?? 0), targetDurationMs))
  const recordedDurationMs = Math.max(0, Number(value.capturedDurationMs ?? 0))
  return {
    percent: Math.round(usableDurationMs / targetDurationMs * 100),
    usableSeconds: Math.floor(usableDurationMs / 1000),
    targetSeconds: Math.floor(targetDurationMs / 1000),
    recordedSeconds: Math.floor(recordedDurationMs / 1000),
    complete: usableDurationMs >= targetDurationMs,
  }
}

export function voiceprintStartGuard(readiness: VoiceprintReadinessModel) {
  if (!readiness.suspectReady || !readiness.canStart) {
    return { disabled: true, reason: '必须先完成嫌疑人声纹注册，才能开始正式语音审讯' }
  }
  return { disabled: false, reason: '' }
}

export function voiceprintModeLabel(mode: VoiceRecognitionMode) {
  const labels: Record<VoiceRecognitionMode, string> = {
    SUSPECT_ONLY: '仅嫌疑人声纹识别',
    SUSPECT_PLUS_INTERROGATOR: '嫌疑人 + 主审民警',
    SUSPECT_PLUS_RECORDER: '嫌疑人 + 记录民警',
    FULL: '嫌疑人 + 主审民警 + 记录民警',
  }
  return labels[mode]
}

/**
 * The mode the runtime will really enforce. `recognitionMode` is only what the
 * bound roles declare; a device without a calibrated margin or threshold
 * degrades to suspect-only, so the operator must never be shown the declared
 * mode as if it were in force. Readiness without injected runtime config carries
 * no effective mode and is not reported as degraded.
 */
export function voiceprintEffectiveMode(readiness: {
  recognitionMode: VoiceRecognitionMode
  effectiveRecognitionMode?: VoiceRecognitionMode
}): VoiceRecognitionMode {
  return readiness.effectiveRecognitionMode ?? readiness.recognitionMode
}

/**
 * Degradation notice shared with `VoiceprintEnrollmentGate.vue`: identical
 * wording, and silent whenever the device honours the declared mode.
 */
export function voiceprintDegradationNotice(readiness: {
  interrogatorReady?: boolean
  recorderReady?: boolean
  recognitionModeDegraded?: boolean
  recognitionModeDegradedReason?: string | null
}): string {
  if (readiness.recognitionModeDegraded !== true) return ''
  if (readiness.interrogatorReady !== true && readiness.recorderReady !== true) return ''
  const detail = readiness.recognitionModeDegradedReason === 'THRESHOLD_NOT_CONFIGURED'
    ? '设备未配置声纹判定阈值'
    : '设备未完成 margin 校准'
  return `已绑定民警声纹，但${detail}，实时识别将退化为仅嫌疑人`
}

export function temporarySpeakerPresentation(speaker: TemporaryAsrSpeaker, speakerName?: string | null) {
  if (speaker === 'SUSPECT') return { label: `嫌疑人 · ${speakerName || '未命名'}`, detail: 'ERes2Net-large 声纹匹配', needsConfirmation: false }
  if (speaker === 'INTERROGATOR') return { label: `主审民警 · ${speakerName || '未命名'}`, detail: 'ERes2Net-large 声纹匹配', needsConfirmation: false }
  if (speaker === 'RECORDER') return { label: `记录民警 · ${speakerName || '未命名'}`, detail: 'ERes2Net-large 声纹匹配', needsConfirmation: false }
  if (speaker === 'OFFICER_FALLBACK') return { label: '民警', detail: '未启用/未匹配民警声纹，按非嫌疑人规则归类', needsConfirmation: false }
  return { label: '说话人待识别', detail: '先保存文字，等待后续声纹分析', needsConfirmation: true }
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import type { OfficerVoiceprint, SessionStatus, VoiceprintEnrollmentState, VoiceprintReadiness } from '../types/interrogation'

const props = defineProps<{
  suspectName: string
  readiness: VoiceprintReadiness
  officers: OfficerVoiceprint[]
  selectedInterrogatorOfficerId: string | null
  selectedRecorderOfficerId: string | null
  enrollmentState: VoiceprintEnrollmentState
  busy: boolean
  sessionStatus: SessionStatus
}>()

defineEmits<{
  suspectStart: []
  suspectStop: []
  selectInterrogator: [officerId: string | null]
  selectRecorder: [officerId: string | null]
  bindRoles: []
}>()

const guard = computed(() => voiceprintStartGuard(props.readiness))
// Task 17A follow-up: the chip states the mode that is actually enforced, never
// the declared one, so it cannot promise officer recognition a margin-less
// device will silently drop.
const modeLabel = computed(() => voiceprintModeLabel(voiceprintEffectiveMode(props.readiness)))
const degradationNotice = computed(() => voiceprintDegradationNotice(props.readiness))
const enrollmentRecording = computed(() => props.enrollmentState.phase === 'RECORDING')
const suspectRecording = computed(() => enrollmentRecording.value && props.enrollmentState.kind === 'SUSPECT')
const finalUsableSeconds = computed(() => Math.floor((props.enrollmentState.usableDurationMs || 0) / 1000))
const enrollmentProgress = computed(() => voiceprintEnrollmentProgress(props.enrollmentState))
const sessionActive = computed(() => ['RUNNING', 'PAUSED'].includes(props.sessionStatus))
const showSuspectProgress = computed(() => props.enrollmentState.phase !== 'IDLE' && props.enrollmentState.kind !== 'OFFICER')
function normalizedSelect(event: Event) {
  const value = (event.target as HTMLSelectElement).value.trim()
  return value || null
}
</script>

<template>
  <section class="voiceprint-preparation-panel" aria-label="声纹准备">
    <header class="voiceprint-preparation-header">
      <div><span class="section-kicker">正式语音审讯前置条件</span><h2>声纹准备</h2></div>
      <div class="voiceprint-mode-chip" :class="{ ready: readiness.suspectReady }">{{ modeLabel }}</div>
    </header>

    <p v-if="degradationNotice" class="voiceprint-mode-degradation" role="status" aria-live="polite" aria-atomic="true">
      <span class="voiceprint-mode-degradation-icon" aria-hidden="true">!</span>
      <span>{{ degradationNotice }}</span>
    </p>

    <div v-if="readiness.simulated" class="voiceprint-warning">当前为浏览器开发模拟；模拟结果不能解锁正式声纹审讯。</div>

    <p class="eres-backend-hint">嫌疑人声纹是开始审讯的唯一必需项。民警声纹和完整校准可选：已匹配的嫌疑人会自动标注，其他声音会保留为待人工确认片段，不会中断浏览器录音或正式审讯。</p>

    <div class="voiceprint-preparation-grid">
      <article class="voiceprint-person-row required">
        <div class="voiceprint-person-main"><strong>嫌疑人 · {{ suspectName || '待录入姓名' }}</strong><span>必须</span></div>
        <div class="voiceprint-status" :class="{ ok: readiness.suspectReady }">{{ readiness.suspectReady ? 'ERes2Net-large 已注册' : 'ERes2Net-large 未注册' }}</div>
        <button v-if="!suspectRecording" class="voiceprint-action primary" :disabled="busy || sessionActive" @click="$emit('suspectStart')">{{ readiness.suspectReady ? '重新录制' : '开始录制' }}</button>
        <button v-else class="voiceprint-action danger" :disabled="busy" @click="$emit('suspectStop')">提前停止并尝试注册</button>
      </article>

      <article class="voiceprint-person-row">
        <div class="voiceprint-person-main"><strong>主审民警</strong><span>从全局声纹库选择</span></div>
        <select :value="selectedInterrogatorOfficerId || ''" :disabled="busy || sessionActive" aria-label="选择主审民警声纹" @change="$emit('selectInterrogator', normalizedSelect($event))">
          <option value="">不启用民警声纹</option>
          <option v-for="officer in officers" :key="officer.officerId" :value="officer.officerId">{{ officer.officerName }} · {{ officer.officerId }}</option>
        </select>
        <span class="voiceprint-status" :class="{ ok: readiness.interrogatorReady }">{{ readiness.interrogatorReady ? '本次已绑定' : '未绑定' }}</span>
      </article>

      <article class="voiceprint-person-row">
        <div class="voiceprint-person-main"><strong>记录民警</strong><span>从全局声纹库选择</span></div>
        <select :value="selectedRecorderOfficerId || ''" :disabled="busy || sessionActive" aria-label="选择记录民警声纹" @change="$emit('selectRecorder', normalizedSelect($event))">
          <option value="">不启用民警声纹</option>
          <option v-for="officer in officers" :key="officer.officerId" :value="officer.officerId">{{ officer.officerName }} · {{ officer.officerId }}</option>
        </select>
        <span class="voiceprint-status" :class="{ ok: readiness.recorderReady }">{{ readiness.recorderReady ? '本次已绑定' : '未绑定' }}</span>
      </article>
    </div>

    <p class="global-library-hint">民警声纹的注册、补录样本、停用和维护统一在“系统设置 → 民警声纹库”完成；案件内只绑定已有档案。</p>

    <div v-if="showSuspectProgress" class="voiceprint-enrollment-progress" :class="enrollmentState.phase.toLowerCase()">
      <strong>嫌疑人声纹</strong>
      <template v-if="enrollmentState.phase === 'RECORDING'">
        <span>请自然说话；有效语音达到 60 秒后会自动停止并注册，停顿和语速慢不会按总时长判失败。</span>
        <div class="voiceprint-capture-meter" role="progressbar" :aria-valuemin="0" :aria-valuemax="enrollmentProgress.targetSeconds" :aria-valuenow="enrollmentProgress.usableSeconds" :aria-label="`有效语音 ${enrollmentProgress.usableSeconds} / ${enrollmentProgress.targetSeconds} 秒`">
          <i :style="{ width: `${enrollmentProgress.percent}%` }"></i>
        </div>
        <small>有效语音 {{ enrollmentProgress.usableSeconds }} / {{ enrollmentProgress.targetSeconds }} 秒</small>
      </template>
      <span v-else-if="enrollmentState.phase === 'PROCESSING'">有效语音已达标，正在进行最终 VAD 复核与 ERes2Net-large 声纹聚合…</span>
      <span v-else>{{ enrollmentState.message }}</span>
      <small v-if="finalUsableSeconds && enrollmentState.phase !== 'RECORDING'">有效语音 {{ finalUsableSeconds }} 秒</small>
    </div>

    <footer class="voiceprint-preparation-footer">
      <div><strong>{{ guard.disabled ? '尚未满足开始条件' : '可以开始正式审讯' }}</strong><span>{{ guard.reason || 'ERes2Net-large 嫌疑人声纹已就绪；角色绑定后冻结本次审讯使用的 reference 版本' }}</span></div>
      <button v-if="sessionStatus === 'READY'" :disabled="busy || guard.disabled" @click="$emit('bindRoles')">保存本次角色选择</button>
    </footer>
  </section>
</template>

<style scoped>
.voiceprint-preparation-panel { padding: 16px 18px; border-bottom: 1px solid var(--line-300); background: linear-gradient(180deg, var(--surface-sunken) 0%, var(--surface-sunken) 100%); color: var(--navy-900); }
.voiceprint-preparation-header,.voiceprint-preparation-footer { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.voiceprint-preparation-header h2 { margin:3px 0 0; font-size:22px; }
.section-kicker { color:var(--ink-500); font-size:12px; letter-spacing:.08em; }
.voiceprint-mode-chip,.voiceprint-status { border:1px solid var(--primary-200); border-radius:999px; padding:5px 10px; background:var(--surface); color:var(--ink-500); font-size:12px; font-weight:700; }
.voiceprint-mode-chip.ready,.voiceprint-status.ok { border-color:var(--success-100); background:var(--success-100); color:var(--success-700); }
.voiceprint-mode-degradation { display:flex; align-items:flex-start; gap:8px; margin:10px 0 0; padding:8px 10px; border:1px solid var(--warning-600); border-left:4px solid var(--warning-600); border-radius:7px; background:var(--warning-100); color:var(--warning-700); font-size:12px; font-weight:700; }
.voiceprint-mode-degradation-icon { display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; width:16px; height:16px; border-radius:50%; background:var(--warning-600); color:var(--surface); font-size:11px; }
.voiceprint-warning { margin-top:10px; padding:9px 12px; border:1px solid var(--warning-600); border-radius:7px; background:var(--warning-100); color:var(--warning-700); font-weight:700; }
.eres-backend-hint { margin:10px 0 0; padding:9px 12px; border:1px solid var(--line-300); border-radius:7px; background:var(--surface); color:var(--ink-500); font-size:12px; }
.voiceprint-preparation-grid { display:grid; gap:8px; margin-top:12px; }
.voiceprint-person-row { display:grid; grid-template-columns:minmax(190px,1fr) minmax(220px,1.4fr) auto; align-items:center; gap:12px; min-height:50px; padding:9px 12px; border:1px solid var(--line-300); border-radius:8px; background:rgba(255,255,255,.9); }
.voiceprint-person-row.required { border-left:4px solid var(--primary-600); }
.voiceprint-person-main { display:flex; align-items:center; gap:8px; }
.voiceprint-person-main > span { color:var(--ink-400); font-size:12px; }
.voiceprint-person-row select { min-height:38px; border:1px solid var(--primary-200); border-radius:6px; padding:0 10px; background:var(--surface); color:var(--ink-700); }
.voiceprint-action,.voiceprint-preparation-footer button { min-height:38px; border:1px solid var(--ink-300); border-radius:6px; padding:0 13px; background:var(--surface); color:var(--ink-700); font-weight:700; }
.voiceprint-action.primary,.voiceprint-preparation-footer > button { border-color:var(--primary-600); background:var(--primary-600); color:var(--surface); }
.voiceprint-action.danger { border-color:var(--danger-700); color:var(--danger-600); }
button:disabled,select:disabled { opacity:.5; }
.global-library-hint { margin:10px 0 0; padding:9px 12px; border:1px solid var(--line-300); border-radius:7px; background:var(--surface); color:var(--ink-500); font-size:12px; }
.voiceprint-capture-meter { height:8px; overflow:hidden; border-radius:999px; background:var(--line-300); flex:1 1 180px; min-width:160px; }
.voiceprint-capture-meter > i { display:block; height:100%; border-radius:inherit; background:var(--primary-600); transition:width .25s ease; }
.voiceprint-enrollment-progress { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-top:10px; padding:9px 12px; border-radius:7px; background:var(--primary-100); color:var(--primary-600); }
.voiceprint-enrollment-progress.error { background:var(--danger-100); color:var(--danger-600); }
.voiceprint-enrollment-progress.complete { background:var(--success-100); color:var(--success-700); }
.voiceprint-enrollment-progress small { margin-left:auto; }
.voiceprint-preparation-footer { margin-top:11px; padding-top:10px; border-top:1px solid var(--line-300); }
.voiceprint-preparation-footer > div { display:grid; gap:3px; }
.voiceprint-preparation-footer span { color:var(--ink-500); font-size:12px; }
@media (max-width:980px) { .voiceprint-person-row { grid-template-columns:1fr; } .voiceprint-preparation-footer,.voiceprint-preparation-header { align-items:flex-start; flex-direction:column; } }
</style>
