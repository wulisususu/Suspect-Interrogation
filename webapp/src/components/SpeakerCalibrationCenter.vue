<script lang="ts">
import type { SpeakerCalibrationStatus } from '../api/speakerCalibration'

export function calibrationTone(status: SpeakerCalibrationStatus): 'ok' | 'warn' | 'danger' | 'muted' {
  if (status === 'VALID') return 'ok'
  if (status === 'RECOMPUTE_RECOMMENDED') return 'warn'
  if (status === 'STALE_MODEL' || status === 'STALE_MIC') return 'danger'
  return 'muted'
}

export function calibrationStatusLabel(status: SpeakerCalibrationStatus): string {
  return {
    NOT_CALIBRATED: '尚未校准',
    VALID: '校准有效',
    STALE_MODEL: 'ERes2Net-large 已更换',
    STALE_MIC: '麦克风已更换',
    RECOMPUTE_RECOMMENDED: '建议重新计算',
    INSUFFICIENT_DATA: '样本不足',
  }[status]
}

export function formatMetric(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : 'UNKNOWN'
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  fetchSpeakerCalibrationHistory,
  fetchSpeakerCalibrationStatus,
  recomputeSpeakerCalibration,
  type SpeakerCalibrationRecord,
  type SpeakerCalibrationState,
} from '../api/speakerCalibration'

const state = ref<SpeakerCalibrationState | null>(null)
const history = ref<SpeakerCalibrationRecord[]>([])
const loading = ref(true)
const recomputing = ref(false)
const error = ref('')
const tone = computed(() => state.value ? calibrationTone(state.value.status) : 'muted')

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [next, rows] = await Promise.all([
      fetchSpeakerCalibrationStatus(),
      fetchSpeakerCalibrationHistory(),
    ])
    state.value = next
    history.value = rows
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取设备校准状态'
  } finally {
    loading.value = false
  }
}

async function recompute() {
  recomputing.value = true
  error.value = ''
  try {
    state.value = await recomputeSpeakerCalibration()
    history.value = await fetchSpeakerCalibrationHistory()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '设备校准失败'
  } finally {
    recomputing.value = false
  }
}

onMounted(() => void refresh())
</script>

<template>
  <section class="calibration-center">
    <div class="center-header">
      <div>
        <h2>设备校准中心</h2>
        <p>ERes2Net-large 的阈值、模型指纹与麦克风兼容语料在此维护。</p>
      </div>
      <button :disabled="loading || recomputing" @click="recompute">
        {{ recomputing ? '正在计算…' : '重新计算 ERes2Net-large 校准' }}
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="loading">正在读取设备校准状态…</p>

    <template v-else-if="state">
      <div class="section-heading"><strong>模型状态</strong><span>ERes2Net-large</span></div>
      <div class="identity-grid">
        <article>
          <span>模型</span>
          <strong>{{ state.currentModel.modelId }} {{ state.currentModel.modelVersion || '' }}</strong>
          <code>{{ state.currentModel.fingerprint.slice(0, 16) }}…</code>
        </article>
        <article>
          <span>生产麦克风</span>
          <strong>{{ state.currentMicrophone.deviceName }}</strong>
          <small>{{ state.currentMicrophone.deviceId }} · {{ state.currentMicrophone.fingerprintCertainty }}</small>
        </article>
        <article>
          <span>当前兼容语料</span>
          <strong>{{ state.currentCorpus.officerCount }} 人 / {{ state.currentCorpus.sampleCount }} 样本</strong>
          <small>{{ state.currentCorpus.ready ? '满足完整校准最低要求' : '尚未达到最低要求' }}</small>
        </article>
      </div>

      <div class="section-heading"><strong>校准状态</strong><span>仅适用于当前 ERes2Net-large 模型与设备</span></div>
      <div class="status-card" :class="`tone-${tone}`">
        <strong>{{ calibrationStatusLabel(state.status) }}</strong>
        <span>{{ state.reason }}</span>
        <small v-if="state.status === 'STALE_MODEL'">旧阈值不会用于新模型指纹；需要重新校准。</small>
        <small v-if="state.status === 'STALE_MIC'">检测到生产麦克风变化；旧设备阈值不会用于新审讯。</small>
        <small v-if="state.status === 'RECOMPUTE_RECOMMENDED'">旧校准仍可使用，建议利用新增样本重新计算。</small>
        <small v-if="state.status === 'INSUFFICIENT_DATA'">完整校准至少需要 {{ state.minimumOfficers }} 名民警，每人至少 {{ state.minimumSamplesPerOfficer }} 个兼容样本。</small>
      </div>

      <div v-if="state.calibration" class="metrics">
        <article><span>Threshold</span><strong>{{ state.calibration.threshold.toFixed(4) }}</strong></article>
        <article><span>Margin</span><strong>{{ state.calibration.margin?.toFixed(4) ?? '—' }}</strong></article>
        <article><span>Observed FAR</span><strong>{{ formatMetric(state.calibration.far) }}</strong></article>
        <article><span>Observed FRR</span><strong>{{ formatMetric(state.calibration.frr) }}</strong></article>
        <article><span>Observed EER</span><strong>{{ formatMetric(state.calibration.eer) }}</strong></article>
        <article><span>校准时间</span><strong>{{ state.calibration.createdAt || '—' }}</strong></article>
      </div>

      <p class="disclaimer">FAR / FRR / EER 是本机有限样本的观测估计，只用于设备参数选择，不代表人口级生物识别认证准确率。</p>

      <section class="history">
        <h3>ERes2Net-large 校准历史</h3>
        <p v-if="history.length === 0">暂无校准历史。</p>
        <div v-for="item in history" :key="item.calibrationId" class="history-row">
          <div><strong>{{ item.createdAt || item.calibrationId }}</strong><span>{{ item.speakerModelId }} · {{ item.microphoneName }}</span></div>
          <div><span>T {{ item.threshold.toFixed(4) }}</span><span>M {{ item.margin?.toFixed(4) ?? '—' }}</span><span>EER {{ formatMetric(item.eer) }}</span><span>{{ item.officerCount }} 人 / {{ item.sampleCount }} 样本</span></div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.calibration-center { display:grid; gap:16px; }
.center-header { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; padding:18px; border:1px solid var(--line-300); border-radius:10px; background:var(--surface); }
.center-header h2 { margin:0 0 6px; }
.center-header p,.status-card span,.status-card small,.identity-grid small { color:var(--ink-500); }
button { min-height:38px; border:1px solid var(--ink-300); border-radius:6px; padding:0 14px; background:var(--surface-sunken); color:var(--ink-700); font-weight:700; }
.section-heading { display:flex; justify-content:space-between; gap:12px; color:var(--ink-500); }.section-heading span { color:var(--ink-400); font-size:12px; }
.identity-grid,.metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
.identity-grid article,.metrics article { display:grid; gap:5px; padding:14px; border:1px solid var(--line-300); border-radius:8px; background:var(--surface); }
.identity-grid span,.metrics span { color:var(--ink-500); font-size:12px; }.identity-grid code { overflow-wrap:anywhere; color:var(--ink-500); font-size:12px; }
.status-card { display:grid; gap:5px; padding:14px 16px; border:1px solid; border-radius:8px; background:var(--surface); }.tone-ok { border-color:var(--success-100); }.tone-warn { border-color:var(--warning-600); background:var(--warning-100); }.tone-danger { border-color:var(--danger-600); background:var(--danger-100); }.tone-muted { border-color:var(--line-300); }
.disclaimer { margin:0; padding:12px 14px; border-radius:8px; background:var(--surface-sunken); color:var(--ink-500); font-size:13px; }
.history { padding:16px; border:1px solid var(--line-300); border-radius:10px; background:var(--surface); }.history h3 { margin-top:0; }.history-row { display:flex; justify-content:space-between; gap:16px; padding:10px 0; border-top:1px solid var(--primary-100); }.history-row > div { display:flex; gap:10px; flex-wrap:wrap; }
.error { color:var(--danger-600); }.loading { color:var(--ink-500); }
@media (max-width:800px) { .center-header { flex-direction:column; } }
</style>
