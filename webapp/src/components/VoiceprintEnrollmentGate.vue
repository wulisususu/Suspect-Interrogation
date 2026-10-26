<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { voiceprintDegradationNotice, voiceprintEnrollmentProgress } from './VoiceprintPreparationPanel.vue'
import type { OfficerVoiceprint, VoiceprintEnrollmentState, VoiceprintReadiness } from '../types/interrogation'

const props = withDefaults(defineProps<{
  suspectName: string
  readiness: VoiceprintReadiness
  officers: OfficerVoiceprint[]
  selectedInterrogatorOfficerId: string | null
  selectedRecorderOfficerId: string | null
  enrollmentState: VoiceprintEnrollmentState
  busy: boolean
  /** Registered suspects get the condensed status card instead of the full recording card. */
  compact?: boolean
}>(), { compact: false })

const emits = defineEmits<{
  suspectStart: []
  suspectStop: []
  selectInterrogator: [officerId: string | null]
  selectRecorder: [officerId: string | null]
  bindRoles: []
}>()

const suspectRecording = computed(() => props.enrollmentState.phase === 'RECORDING' && props.enrollmentState.kind === 'SUSPECT')
const showProgress = computed(() => props.enrollmentState.phase !== 'IDLE' && props.enrollmentState.kind !== 'OFFICER')
const progress = computed(() => voiceprintEnrollmentProgress({
  ...props.enrollmentState,
  usableSpeechMs: props.enrollmentState.usableDurationMs,
  requiredUsableSpeechMs: props.enrollmentState.targetDurationMs,
}))
const finalUsableSeconds = computed(() => Math.floor((props.enrollmentState.usableDurationMs || 0) / 1000))
function normalizedSelect(event: Event) {
  const value = (event.target as HTMLSelectElement).value.trim()
  return value || null
}
const liveStatus = computed(() => {
  if (props.enrollmentState.phase === 'RECORDING') return `正在采集嫌疑人有效语音，当前有效语音 ${progress.value.usableSeconds} / ${progress.value.targetSeconds} 秒。`
  if (props.enrollmentState.phase === 'PROCESSING') return '正在进行最终声纹注册，请稍候。'
  if (props.enrollmentState.phase === 'ERROR') return `声纹注册失败：${props.enrollmentState.message || '请检查麦克风连接后重新录制。'}`
  if (props.enrollmentState.phase === 'COMPLETE') return '声纹注册完成，已解锁正式审讯与实时对话。'
  return props.enrollmentState.message || ''
})

// A failed re-recording must never read as if the already registered voiceprint was lost: the
// backend only calls replace_suspect after the new quality checks passed, so the previous
// reference keeps working. Keep reporting that instead of showing a bare failure.
const reEnrollFailure = computed(() => props.readiness.suspectReady && props.enrollmentState.phase === 'ERROR')
const reEnrollLabel = computed(() => (reEnrollFailure.value ? '再次重新录制' : '重新录制'))
const registeredLabel = computed(() => (reEnrollFailure.value ? '✓ 当前已有声纹仍然有效' : '✓ 已注册'))
const suspectRowClass = computed(() => (props.compact ? 'suspect-row compact' : 'suspect-row'))

// Prefer the registered reference measurement from readiness; fall back to whatever this
// session most recently measured while enrolling.
const referenceUsableSeconds = computed(() => {
  const durationMs = Number(props.readiness.usableDurationMs || 0)
  return durationMs > 0 ? Number((durationMs / 1000).toFixed(2)) : 0
})

function measuredUsableSeconds() {
  const measured = Number(props.enrollmentState.usableDurationMs || 0)
  return measured > 0 ? Number((measured / 1000).toFixed(2)) : 0
}

// The compact card reports the duration it can see and keeps the last known value instead
// of dropping the line when a later attempt has no measurement. `watch` (not a `computed`)
// owns that memory: a computed must stay a pure function of its inputs.
const lastMeasuredUsableSecondsRef = ref(0)
watch(() => props.enrollmentState.usableDurationMs, (durationMs) => {
  const measured = Number(durationMs || 0)
  if (measured > 0) lastMeasuredUsableSecondsRef.value = Number((measured / 1000).toFixed(2))
})

const compactUsableSpeechLabel = computed(() => {
  const measured = measuredUsableSeconds()
  const seconds = [referenceUsableSeconds.value, measured, lastMeasuredUsableSecondsRef.value].find((value) => value > 0) || 0
  return seconds > 0 ? `有效语音：${seconds} 秒` : '有效语音：以本次注册结果为准'
})

const compactQualityLabel = computed(() => (props.readiness.enrollmentQuality ? `质量：${props.readiness.enrollmentQuality}` : '质量：未知'))

// Task 17B-1: the operator must know when the declared mode is not the enforced
// one. The notice wording lives in `voiceprintDegradationNotice` so this gate
// and the voiceprint preparation panel cannot drift apart.
const officerRolesBound = computed(() => props.readiness.interrogatorReady === true || props.readiness.recorderReady === true)
const degradationNotice = computed(() => (officerRolesBound.value ? voiceprintDegradationNotice(props.readiness) : ''))

function startOrReRecord() {
  emits('suspectStart')
}
</script>

<template>
  <div v-if="!compact" class="capture-page-content">
    <section class="capture-card" aria-label="嫌疑人声纹注册">
      <header class="capture-heading"><div><span class="section-kicker">正式审讯前置条件</span><h2>完成嫌疑人声纹注册</h2></div><span class="capture-state" :class="{ ready: readiness.suspectReady, recording: suspectRecording }">{{ suspectRecording ? '有效语音累计中' : enrollmentState.phase === 'PROCESSING' ? '正在注册' : readiness.suspectReady ? '声纹已注册' : '尚未注册' }}</span></header>
      <p class="capture-identity">嫌疑人 · {{ suspectName || '待录入姓名' }}<span>完成声纹注册后，即可解锁正式审讯与实时对话。</span></p>
      <div class="speech-measure"><strong>{{ readiness.suspectReady && enrollmentState.phase === 'IDLE' ? referenceUsableSeconds : progress.usableSeconds }}</strong><span>/ {{ progress.targetSeconds }} 秒 · 有效语音<br /><small>达到目标时长后自动停止采集并进行声纹注册</small></span></div>
      <div class="speech-track" role="progressbar" aria-label="嫌疑人有效语音采集进度" :aria-valuemin="0" :aria-valuemax="progress.targetSeconds" :aria-valuenow="readiness.suspectReady && enrollmentState.phase === 'IDLE' ? Math.min(referenceUsableSeconds, progress.targetSeconds) : progress.usableSeconds"><i :style="{ width: (readiness.suspectReady && enrollmentState.phase === 'IDLE' ? Math.min(100, referenceUsableSeconds / progress.targetSeconds * 100) : progress.percent) + '%' }"></i></div>
      <p class="speech-caption">有效语音 {{ readiness.suspectReady && enrollmentState.phase === 'IDLE' ? referenceUsableSeconds : progress.usableSeconds }} / {{ progress.targetSeconds }} 秒<span>静音和长时间停顿不计入有效时长</span></p>
      <div v-if="showProgress" class="capture-result" :class="enrollmentState.phase.toLowerCase()"><p class="voiceprint-enrollment-status" role="status" aria-live="polite" aria-atomic="true">{{ liveStatus }}</p><span v-if="enrollmentState.phase === 'PROCESSING'">正在复核有效语音并生成声纹，请稍候。</span><span v-else-if="enrollmentState.phase === 'COMPLETE'">质量：{{ readiness.enrollmentQuality || '以注册结果为准' }} · 有效语音 {{ finalUsableSeconds }} 秒</span><span v-if="reEnrollFailure">当前已有声纹仍然有效</span></div>
      <p v-if="readiness.simulated" class="capture-simulation">当前为开发模拟，模拟结果不能解锁正式审讯。</p>
    </section>
    <slot name="guide" />
    <footer class="capture-actions"><button v-if="!suspectRecording" class="primary" :disabled="busy || enrollmentState.phase === 'PROCESSING'" @click="startOrReRecord">{{ readiness.suspectReady ? reEnrollLabel : '开始录制' }}</button><button v-else class="danger" :disabled="busy" @click="emits('suspectStop')">提前停止并尝试注册</button><slot name="return" /></footer>
    <p v-if="degradationNotice" class="voiceprint-mode-degradation" role="status" aria-live="polite" aria-atomic="true">{{ degradationNotice }}</p>
    <details class="optional-officer-binding capture-binding"><summary>可选：绑定民警声纹</summary><p>嫌疑人声纹是唯一必需项；不选择民警声纹仍可开始正式审讯。</p><div class="role-binding-grid"><label>主审民警<select :value="selectedInterrogatorOfficerId || ''" :disabled="busy || suspectRecording" aria-label="选择主审民警声纹" @change="emits('selectInterrogator', normalizedSelect($event))"><option value="">不启用民警声纹</option><option v-for="officer in officers" :key="officer.officerId" :value="officer.officerId">{{ officer.officerName }} · {{ officer.officerId }}</option></select></label><label>记录民警<select :value="selectedRecorderOfficerId || ''" :disabled="busy || suspectRecording" aria-label="选择记录民警声纹" @change="emits('selectRecorder', normalizedSelect($event))"><option value="">不启用民警声纹</option><option v-for="officer in officers" :key="officer.officerId" :value="officer.officerId">{{ officer.officerName }} · {{ officer.officerId }}</option></select></label><button :disabled="busy || suspectRecording" @click="emits('bindRoles')">保存本次角色选择</button></div></details>
  </div>
  <aside v-else class="voiceprint-enrollment-gate" :class="{ compact }" aria-label="嫌疑人声纹注册">
    <div class="voiceprint-enrollment-content" :class="{ 'compact-card': compact }">
      <div :class="suspectRowClass">
        <div class="suspect-identity">
          <strong>嫌疑人 · {{ suspectName || '待录入姓名' }}</strong>
          <span :class="{ ready: readiness.suspectReady }">{{ compact ? registeredLabel : readiness.suspectReady ? '声纹已注册' : '尚未注册' }}</span>
        </div>
        <dl v-if="compact">
          <dt>{{ compactQualityLabel }}</dt>
          <dt>{{ compactUsableSpeechLabel }}</dt>
        </dl>
        <button v-if="!suspectRecording" class="primary" :disabled="busy" @click="startOrReRecord">{{ compact ? reEnrollLabel : '开始录制' }}</button>
        <button v-else class="danger" :disabled="busy" @click="emits('suspectStop')">提前停止并尝试注册</button>
      </div>

      <p v-if="degradationNotice" class="voiceprint-mode-degradation" role="status" aria-live="polite" aria-atomic="true">
        <span class="voiceprint-mode-degradation-icon" aria-hidden="true">!</span>
        <span>{{ degradationNotice }}</span>
      </p>

      <details class="optional-officer-binding">
        <summary>可选：绑定民警声纹</summary>
        <p>嫌疑人声纹是唯一必需项；不选择民警声纹仍可开始正式审讯。</p>
        <label>
          主审民警
          <select :value="selectedInterrogatorOfficerId || ''" :disabled="busy" aria-label="选择主审民警声纹" @change="emits('selectInterrogator', normalizedSelect($event))">
            <option value="">不启用民警声纹</option>
            <option v-for="officer in officers" :key="officer.officerId" :value="officer.officerId">{{ officer.officerName }} · {{ officer.officerId }}</option>
          </select>
        </label>
        <label>
          记录民警
          <select :value="selectedRecorderOfficerId || ''" :disabled="busy" aria-label="选择记录民警声纹" @change="emits('selectRecorder', normalizedSelect($event))">
            <option value="">不启用民警声纹</option>
            <option v-for="officer in officers" :key="officer.officerId" :value="officer.officerId">{{ officer.officerName }} · {{ officer.officerId }}</option>
          </select>
        </label>
        <button :disabled="busy" @click="emits('bindRoles')">保存本次角色选择</button>
      </details>

      <div v-if="showProgress" class="voiceprint-enrollment-progress" :class="enrollmentState.phase.toLowerCase()">
        <template v-if="enrollmentState.phase === 'RECORDING'">
          <span>请自然说话；有效语音达到 60 秒后会自动停止并注册，停顿和语速慢不会按总时长判失败。</span>
          <div class="voiceprint-capture-meter" role="progressbar" :aria-valuemin="0" :aria-valuemax="progress.targetSeconds" :aria-valuenow="progress.usableSeconds" :aria-label="`有效语音 ${progress.usableSeconds} / ${progress.targetSeconds} 秒`">
            <i :style="{ width: `${progress.percent}%` }"></i>
          </div>
          <small>有效语音 {{ progress.usableSeconds }} / {{ progress.targetSeconds }} 秒</small>
        </template>
        <span v-else-if="enrollmentState.phase === 'PROCESSING'">有效语音已达标，正在进行最终声纹注册…</span>
        <span v-else>{{ enrollmentState.message }}</span>
        <small v-if="finalUsableSeconds && enrollmentState.phase !== 'RECORDING'">有效语音 {{ finalUsableSeconds }} 秒</small>
      </div>

      <p v-if="showProgress" class="voiceprint-enrollment-status" role="status" aria-live="polite" aria-atomic="true">{{ liveStatus }}</p>
    </div>
  </aside>
</template>

<style scoped>
.voiceprint-enrollment-gate { overflow:hidden; border:1px solid var(--line-300); border-radius:10px; background:var(--surface-sunken); color:var(--navy-900); }
.voiceprint-enrollment-content { padding:16px 18px; }
header h2 { margin:3px 0 0; font-size:22px; }
header p { margin:8px 0 0; color:var(--ink-500); }
.section-kicker { color:var(--ink-500); font-size:12px; letter-spacing:.08em; }
.suspect-row { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:14px; padding:12px; border:1px solid var(--line-300); border-left:4px solid var(--primary-600); border-radius:8px; background:var(--surface); }
.suspect-row > div { display:grid; gap:5px; }
.suspect-row span { color:var(--ink-500); font-size:12px; font-weight:700; }
.suspect-row span.ready { color:var(--success-700); }
.voiceprint-mode-degradation { display:flex; align-items:flex-start; gap:8px; margin:8px 0 0; padding:8px 10px; border:1px solid var(--warning-600); border-left:4px solid var(--warning-600); border-radius:7px; background:var(--warning-100); color:var(--warning-700); font-size:12px; font-weight:700; }
.voiceprint-mode-degradation-icon { display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; width:16px; height:16px; border-radius:50%; background:var(--warning-600); color:var(--surface); font-size:11px; }
.optional-officer-binding { margin-top:12px; padding:9px 12px; border:1px solid var(--line-300); border-radius:8px; background:var(--surface); color:var(--ink-500); }
.optional-officer-binding summary { cursor:pointer; color:var(--primary-600); font-weight:700; }
.optional-officer-binding p { margin:9px 0; font-size:12px; }
.optional-officer-binding label { display:grid; gap:4px; margin-top:8px; color:var(--primary-600); font-size:12px; font-weight:700; }
.optional-officer-binding select { min-height:34px; border:1px solid var(--primary-200); border-radius:6px; padding:0 8px; background:var(--surface); color:var(--ink-700); }
.optional-officer-binding button { margin-top:10px; }
button { min-height:38px; border:1px solid var(--ink-300); border-radius:6px; padding:0 13px; background:var(--surface); color:var(--ink-700); font-weight:700; }
button.primary { border-color:var(--primary-600); background:var(--primary-600); color:var(--surface); }
button.danger { border-color:var(--danger-700); color:var(--danger-600); }
button:disabled { opacity:.5; }
.voiceprint-enrollment-progress { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-top:10px; padding:9px 12px; border-radius:7px; background:var(--primary-100); color:var(--primary-600); }
.voiceprint-enrollment-progress.error { background:var(--danger-100); color:var(--danger-600); }
.voiceprint-enrollment-progress.complete { background:var(--success-100); color:var(--success-700); }
.voiceprint-capture-meter { height:8px; flex:1 1 180px; min-width:160px; overflow:hidden; border-radius:999px; background:var(--line-300); }
.voiceprint-capture-meter > i { display:block; height:100%; border-radius:inherit; background:var(--primary-600); transition:width .25s ease; }
.voiceprint-enrollment-progress small { margin-left:auto; }
.voiceprint-enrollment-status { margin:8px 0 0; color:var(--ink-500); font-size:13px; }
/* Registered suspects keep the same card, condensed: one status row plus a collapsible role drawer. */
.compact-card { padding:10px 12px; }
.compact-card .suspect-row { flex-wrap:wrap; gap:8px 14px; margin-top:0; padding:8px 10px; border-left-width:3px; }
.compact-card .suspect-row dl { display:flex; flex-wrap:wrap; gap:4px 14px; margin:0; color:var(--ink-500); font-size:12px; font-weight:700; }
.compact-card .suspect-row dt { margin:0; }
.compact-card .suspect-identity { flex:1 1 140px; }
.compact-card button { min-height:30px; padding:0 11px; font-size:12px; }
.compact-card .optional-officer-binding { margin-top:8px; padding:6px 9px; }
.compact-card .optional-officer-binding button { margin-top:7px; }
.compact-card .voiceprint-enrollment-progress { margin-top:8px; padding:7px 9px; font-size:12px; }
.compact-card .voiceprint-enrollment-status { margin-top:6px; font-size:12px; }
@media (max-width:980px) { .suspect-row { align-items:flex-start; flex-direction:column; } }

.capture-page-content { display:grid; gap:18px; color:var(--ink-700); min-width:0; font-size:15px; }
.capture-card { background:var(--surface); padding:24px; border-radius:13px; }
.capture-heading { display:flex; align-items:center; justify-content:space-between; gap:18px; }.capture-heading h2 { font-size:21px; margin:6px 0 0; color:var(--ink-700); }.capture-heading .section-kicker { font-size:13px; color:var(--ink-400); letter-spacing:0; }
.capture-state { background:var(--surface-sunken); color:var(--ink-400); border-radius:20px; padding:7px 13px; font-size:13px; white-space:nowrap; }.capture-state.recording { background:var(--warning-100); color:var(--warning-600); }.capture-state.ready { background:var(--success-100); color:var(--success-700); }
.capture-identity { display:flex; flex-wrap:wrap; gap:10px 20px; margin:16px 0 0; font-weight:600; color:var(--ink-700); }.capture-identity > span { font-size:14px; color:var(--ink-400); font-weight:400; }
.speech-measure { display:flex; align-items:center; gap:18px; margin:20px 0 18px; }.speech-measure > strong { font-size:52px; line-height:1.15; color:var(--primary-600); font-variant-numeric:tabular-nums; }.speech-measure > span { line-height:1.9; color:var(--ink-400); font-size:15px; }.speech-measure small { font-size:13px; color:var(--ink-400); }
.speech-track { height:16px; background:var(--primary-100); overflow:hidden; border-radius:20px; }.speech-track i { display:block; height:100%; background:var(--primary-600); border-radius:inherit; transition:width .25s; }
.speech-caption { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; font-size:14px; color:var(--primary-600); margin:14px 0 0; }.speech-caption > span { color:var(--ink-400); font-size:13px; }
.capture-result { margin-top:14px; padding:12px 18px; border-radius:8px; background:var(--surface-sunken); font-size:14px; color:var(--primary-600); }.capture-result .voiceprint-enrollment-status { color:inherit; margin:0; font-size:14px; line-height:1.8; }.capture-result > span { display:block; margin-top:7px; }.capture-result.error { background:var(--danger-100); color:var(--danger-600); }.capture-result.complete { background:var(--success-100); color:var(--success-700); }.capture-simulation { color:var(--warning-600); background:var(--warning-100); padding:12px; border-radius:8px; font-size:14px; }
.capture-actions { display:flex; justify-content:space-between; align-items:center; gap:16px; }.capture-actions button { min-height:52px; padding:0 30px; font-size:15px; font-family:inherit; border-radius:9px; }.capture-actions button.primary { background:var(--primary-600); border-color:var(--primary-600); }.capture-actions button.danger { background:var(--surface); border-color:var(--danger-100); }
.capture-binding { margin-top:0; padding:20px 24px; background:var(--surface); border:0; border-radius:13px; }.capture-binding summary { font-size:15px; color:var(--primary-600); }.capture-binding p { margin:16px 0; font-size:14px; color:var(--ink-400); }.role-binding-grid { display:grid; grid-template-columns:1fr 1fr auto; gap:18px; align-items:end; }.capture-binding label { margin-top:0; gap:9px; font-size:14px; }.capture-binding select { font:inherit; min-height:44px; border-color:var(--line-300); background:var(--surface-sunken); }.capture-binding button { font:inherit; min-height:44px; margin:0; border-color:var(--line-300); color:var(--primary-600); }
.capture-page-content button:focus-visible,.capture-page-content select:focus-visible,.capture-page-content summary:focus-visible { outline:3px solid var(--ink-300); outline-offset:3px; }
@media(max-width:900px) { .role-binding-grid { grid-template-columns:1fr; }.capture-card { padding:22px; }.capture-heading { align-items:flex-start; }.capture-heading h2 { font-size:19px; } }
@media(max-width:600px) { .capture-actions { flex-direction:column; align-items:stretch; }.capture-heading { flex-direction:column; }.speech-measure { gap:12px; }.speech-measure > strong { font-size:44px; } }
</style>
