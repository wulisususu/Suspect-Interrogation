<script lang="ts">
import type { OfficerVoiceProfile as FilterableOfficerVoiceProfile } from '../api/officerVoiceprints'

export function filterOfficerProfiles(profiles: FilterableOfficerVoiceProfile[], query: string): FilterableOfficerVoiceProfile[] {
  const needle = String(query || '').trim().toLowerCase()
  if (!needle) return profiles
  return profiles.filter((item) =>
    item.officerId.toLowerCase().includes(needle) || item.officerName.toLowerCase().includes(needle),
  )
}

export function formatVoiceprintDuration(durationMs: number): string {
  const seconds = Math.max(0, Number(durationMs || 0)) / 1000
  return `${seconds.toFixed(1)} 秒`
}

/**
 * A transport failure that arrives while this round is being finalized is the
 * normal end of the recording, not a failure: the backend stores the sample and
 * closes the browser audio channel while the HTTP stop/enroll request is still
 * running. Reporting that close as an error told the operator a saved sample had
 * failed. Returns the message to show, or `''` when it must be ignored.
 *
 * `pause()` on the transport already silences the main cause; this guard covers
 * the window between `pause()` and the backend actually tearing the channel
 * down, where the close callback still fires.
 */
export function captureFailureNotice(message: string, settling: boolean): string {
  return settling ? '' : message
}
</script>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  disableOfficerVoiceSample,
  fetchOfficerVoiceProfile,
  fetchOfficerVoiceProfiles,
  revokeOfficerVoiceProfile,
  type OfficerVoiceProfile,
} from '../api/officerVoiceprints'
import {
  fetchBrowserAwareVoiceprintStatus,
  startBrowserAwareOfficerEnrollment,
  stopBrowserAwareOfficerEnrollment,
} from '../api/browserVoiceprint'
import type { BrowserVoiceprintCapture } from '../audio/browserVoiceprintCapture'
import { selectVoiceprintSource } from '../audio/voiceprintSourceSelection'
import { audioInputMode } from '../config/audioInput'

const profiles = ref<OfficerVoiceProfile[]>([])
const selectedOfficerId = ref('')
const search = ref('')
const officerIdInput = ref('')
const officerNameInput = ref('')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')
const recording = ref(false)
const captureSubjectId = ref('')
const captureId = ref('')
const capturedDurationMs = ref(0)
const usableSpeechMs = ref(0)
const requiredUsableSpeechMs = ref(60_000)
const captureSource = ref<'ALSA' | 'BROWSER'>('ALSA')
let browserCapture: BrowserVoiceprintCapture | null = null
let progressTimer: ReturnType<typeof setInterval> | null = null
let finalizing = false

const filteredProfiles = computed(() => filterOfficerProfiles(profiles.value, search.value))
const selectedProfile = computed(() => profiles.value.find((item) => item.officerId === selectedOfficerId.value) || null)
const inputModeText = computed(() => audioInputMode === 'BROWSER' ? '浏览器麦克风' : '一体机麦克风')
const activeProfiles = computed(() => profiles.value.filter((item) => item.active))
const totalSamples = computed(() => activeProfiles.value.reduce((total, item) => total + item.sampleCount, 0))
const totalSpeechMs = computed(() => activeProfiles.value.reduce((total, item) => total + item.usableDurationMs, 0))
const enrollmentForm = ref<HTMLElement | null>(null)
const enrollmentOpen = ref(false)
let enrollmentReturnFocus: HTMLElement | null = null

async function openEnrollment(profile?: OfficerVoiceProfile) {
  if (busy.value || recording.value) return
  enrollmentReturnFocus = typeof document !== 'undefined' && document.activeElement instanceof HTMLElement ? document.activeElement : null
  officerIdInput.value = profile?.officerId || ''
  officerNameInput.value = profile?.officerName || ''
  clearNotice()
  enrollmentOpen.value = true
  await nextTick()
  enrollmentForm.value?.querySelector?.('input')?.focus({ preventScroll: true })
}

function closeEnrollment() {
  if (busy.value || recording.value) return
  enrollmentOpen.value = false
  enrollmentReturnFocus?.focus()
}

function enrollmentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); closeEnrollment(); return }
  if (event.key !== 'Tab') return
  const items = Array.from(enrollmentForm.value?.querySelectorAll<HTMLElement>('input:not(:disabled),button:not(:disabled),[tabindex="0"]') || [])
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
const progressPercent = computed(() => {
  const target = Math.max(1, requiredUsableSpeechMs.value)
  return Math.min(100, Math.round(usableSpeechMs.value / target * 100))
})

function clearNotice() {
  error.value = ''
  message.value = ''
}

function stopPolling() {
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = null
}

async function refresh(preferredOfficerId?: string) {
  loading.value = true
  try {
    profiles.value = await fetchOfficerVoiceProfiles(false)
    const preferred = preferredOfficerId || selectedOfficerId.value
    if (preferred && profiles.value.some((item) => item.officerId === preferred)) {
      selectedOfficerId.value = preferred
    } else if (!selectedOfficerId.value && profiles.value.length) {
      selectedOfficerId.value = profiles.value[0]!.officerId
    } else if (selectedOfficerId.value && !profiles.value.some((item) => item.officerId === selectedOfficerId.value)) {
      selectedOfficerId.value = profiles.value[0]?.officerId || ''
    }
    if (selectedOfficerId.value) await refreshDetail(selectedOfficerId.value, false)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function refreshDetail(officerId: string, setBusy = true) {
  if (!officerId) return
  if (setBusy) busy.value = true
  try {
    const detail = await fetchOfficerVoiceProfile(officerId)
    const index = profiles.value.findIndex((item) => item.officerId === officerId)
    if (index >= 0) profiles.value.splice(index, 1, detail)
    else profiles.value.push(detail)
    selectedOfficerId.value = officerId
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (setBusy) busy.value = false
  }
}

function selectProfile(profile: OfficerVoiceProfile) {
  clearNotice()
  selectedOfficerId.value = profile.officerId
  officerIdInput.value = profile.officerId
  officerNameInput.value = profile.officerName
  void refreshDetail(profile.officerId)
}

async function pollCapture() {
  if (!recording.value || finalizing) return
  try {
    const status = await fetchBrowserAwareVoiceprintStatus()
    capturedDurationMs.value = Number(status.capturedDurationMs ?? status.recordedDurationMs ?? 0)
    usableSpeechMs.value = Number(status.usableSpeechMs ?? 0)
    requiredUsableSpeechMs.value = Number(status.requiredUsableSpeechMs ?? status.targetDurationMs ?? 60_000)
    if (status.complete) await finalizeSample(true)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function beginSample() {
  const officerId = officerIdInput.value.trim()
  const officerName = officerNameInput.value.trim()
  if (!officerId || !officerName || busy.value || recording.value) return
  clearNotice()
  busy.value = true
  try {
    const selection = await selectVoiceprintSource(audioInputMode)
    captureSource.value = selection.source
    browserCapture = selection.browserCapture
    const started = await startBrowserAwareOfficerEnrollment(officerId, officerName, selection.source)
    if (!started.captureId) throw new Error('后端未返回声纹采集会话编号')
    captureSubjectId.value = officerId
    captureId.value = started.captureId
    capturedDurationMs.value = 0
    usableSpeechMs.value = 0
    requiredUsableSpeechMs.value = 60_000
    if (browserCapture) {
      await browserCapture.start(started.captureId, {
        onError: (text) => {
          const notice = captureFailureNotice(text, finalizing)
          if (notice) error.value = notice
        },
        onTrackEnded: () => {
          const notice = captureFailureNotice('浏览器麦克风已停止，请重新开始采样', finalizing)
          if (notice) error.value = notice
        },
      })
    }
    recording.value = true
    stopPolling()
    progressTimer = setInterval(() => { void pollCapture() }, 500)
    await pollCapture()
  } catch (cause) {
    try { await browserCapture?.stop() } catch { /* cleanup only */ }
    browserCapture = null
    captureId.value = ''
    captureSubjectId.value = ''
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
}

async function finalizeSample(automatic = false) {
  if (!recording.value || finalizing || !captureSubjectId.value) return
  finalizing = true
  busy.value = true
  stopPolling()
  // From here on the transport close is expected, and any notice written before
  // this point belongs to a superseded failure: the successful sample below is
  // the current state.
  error.value = ''
  const officerId = captureSubjectId.value
  try {
    browserCapture?.pause()
    const result = await stopBrowserAwareOfficerEnrollment(officerId)
    await browserCapture?.stop()
    browserCapture = null
    recording.value = false
    captureId.value = ''
    captureSubjectId.value = ''
    message.value = automatic ? '有效语音已达标，新样本已自动添加并重新聚合。' : '新样本已添加并重新聚合。'
    await refresh(officerId)
    officerIdInput.value = result.officerId ? String(result.officerId) : officerId
    officerNameInput.value = result.officerName ? String(result.officerName) : officerNameInput.value
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    try { await browserCapture?.stop() } catch { /* cleanup only */ }
    browserCapture = null
    recording.value = false
    captureId.value = ''
    captureSubjectId.value = ''
  } finally {
    finalizing = false
    busy.value = false
  }
}

async function disableSample(sampleId: string) {
  const profile = selectedProfile.value
  if (!profile || busy.value || recording.value) return
  clearNotice()
  busy.value = true
  try {
    await disableOfficerVoiceSample(profile.officerId, sampleId, '系统设置中人工停用')
    message.value = '样本已保留在历史记录中并停用，聚合 reference 已重建。'
    await refresh(profile.officerId)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
}

async function revokeProfile() {
  const profile = selectedProfile.value
  if (!profile || busy.value || recording.value) return
  clearNotice()
  busy.value = true
  try {
    await revokeOfficerVoiceProfile(profile.officerId)
    message.value = '该民警声纹档案已停用；已冻结的历史审讯 reference 不受影响。'
    await refresh(profile.officerId)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
}

onMounted(() => { void refresh() })
onUnmounted(() => {
  stopPolling()
  void browserCapture?.stop()
  browserCapture = null
})
</script>

<template>
  <section class="officer-library" aria-label="民警声纹库">
    <div class="library-main">
      <header class="library-header">
        <div><h2>民警声纹库</h2><p>已登记 {{ activeProfiles.length }} 人 · 有效样本 {{ totalSamples }} 条 · 有效语音 {{ formatVoiceprintDuration(totalSpeechMs) }} · 跨案件复用</p></div>
        <div class="library-actions"><input v-model="search" placeholder="按姓名或编号搜索" aria-label="搜索民警声纹档案" /><button class="primary" :disabled="busy || recording" @click="openEnrollment()">新增声纹登记</button></div>
      </header>
      <div v-if="error" class="notice error" role="alert">{{ error }}</div>
      <div v-else-if="message" class="notice success" aria-live="polite">{{ message }}</div>
      <section class="library-card profile-list-panel" aria-label="民警档案">
        <div v-if="loading" class="empty-state" role="status">正在加载…</div>
        <div v-else-if="!filteredProfiles.length" class="empty-state">{{ search.trim() ? '暂无匹配的民警声纹档案，请调整姓名或编号' : '尚未登记民警声纹，点击新增声纹登记开始采集' }}</div>
        <div v-else class="table-scroll">
          <table class="profiles-table"><thead><tr><th>民警</th><th>警号 / 编号</th><th>有效样本</th><th>有效时长</th><th>最近更新</th><th>状态</th></tr></thead>
            <tbody><tr v-for="profile in filteredProfiles" :key="profile.profileId" :class="{ selected: selectedOfficerId === profile.officerId }">
              <td><button class="profile-select" :aria-pressed="selectedOfficerId === profile.officerId" :disabled="busy || recording" @click="selectProfile(profile)">{{ profile.officerName }}<small>{{ selectedOfficerId === profile.officerId ? '正在查看' : '查看样本' }}</small></button></td>
              <td>{{ profile.officerId }}</td><td>{{ profile.sampleCount }} 条</td><td>{{ formatVoiceprintDuration(profile.usableDurationMs) }}</td><td>{{ profile.updatedAt ? new Date(profile.updatedAt).toLocaleString() : '未提供' }}</td><td><span class="status-chip" :class="{ inactive: !profile.active }">{{ profile.active ? '使用中' : '已停用' }}</span></td>
            </tr></tbody>
          </table>
        </div>
        <p class="card-note">选择民警查看样本；登记后可在新建询问时直接选用。</p>
      </section>
      <section class="library-card profile-detail-panel" aria-label="样本明细">
        <header class="card-heading"><h3>{{ selectedProfile ? selectedProfile.officerName + ' · 样本明细' : '样本明细' }}</h3><span v-if="selectedProfile">聚合版本 v{{ selectedProfile.aggregateVersion }} · 样本变更后自动重建</span></header>
        <div v-if="!selectedProfile" class="empty-state">选择一名民警查看保留样本。</div>
        <template v-else>
          <div v-if="!selectedProfile.samples?.length" class="empty-state">暂无样本明细</div>
          <div v-else class="table-scroll">
            <table class="samples-table"><thead><tr><th>样本编号</th><th>质量</th><th>有效时长</th><th>采样设备</th><th>采样信息</th><th>操作</th></tr></thead>
              <tbody><tr v-for="sample in selectedProfile.samples" :key="sample.sampleId" :class="{ inactive: !sample.active }">
                <td class="sample-id" :title="sample.sampleId">{{ sample.sampleId.slice(0, 8) }}</td><td><span class="quality-label" :class="{ good: sample.quality === 'GOOD' }">{{ sample.quality }}</span></td><td>{{ formatVoiceprintDuration(sample.usableDurationMs) }}</td><td>{{ sample.deviceName || sample.deviceId || '未知设备' }}</td>
                <td><details class="sample-metadata"><summary>查看详情</summary><dl><div><dt>完整样本编号</dt><dd>{{ sample.sampleId }}</dd></div><div><dt>采样时间</dt><dd>{{ sample.capturedAt ? new Date(sample.capturedAt).toLocaleString() : '未提供' }}</dd></div><div><dt>音源</dt><dd>{{ sample.audioSource }}</dd></div><div><dt>模型</dt><dd>{{ sample.modelId }} {{ sample.modelVersion || '' }}</dd></div></dl></details></td>
                <td><button v-if="sample.active" class="ghost" :disabled="busy || recording" @click="disableSample(sample.sampleId)">停用样本</button><span v-else class="disabled-reason">{{ sample.disabledReason || '已停用' }}</span></td>
              </tr></tbody>
            </table>
          </div>
          <footer class="detail-footer"><p>停用样本后不再参与说话人比对，历史记录继续保留。</p><div class="detail-actions"><button :disabled="busy || recording" @click="openEnrollment(selectedProfile)">为该民警补录样本</button><button class="danger ghost" :disabled="busy || recording || !selectedProfile.active" @click="revokeProfile">停用该民警</button></div></footer>
        </template>
      </section>
      <Teleport to="body"><div v-if="enrollmentOpen" class="voice-enrollment-overlay" @keydown="enrollmentKeydown"><section ref="enrollmentForm" class="library-card sample-enrollment-card" role="dialog" aria-modal="true" aria-labelledby="officer-enrollment-title">
        <div class="card-heading"><h3 id="officer-enrollment-title">新增声纹登记 · 添加新样本</h3><button class="close-enrollment" :disabled="busy || recording" aria-label="关闭声纹登记弹窗" @click="closeEnrollment">关闭</button></div>
        <div v-if="error" class="notice error" role="alert">{{ error }}</div><div v-else-if="message" class="notice success" role="status">{{ message }}</div>
        <p v-if="recording" class="recording-chip">正在采样，请保持自然、连续说话</p>
        <p class="enrollment-steps">填写或选择民警 → 自然、连续说话 → 有效语音达标后自动完成登记</p>
        <p class="enrollment-hint">同一民警可持续补录；静音与停顿不计入有效语音。采集音源：{{ inputModeText }}。</p>
        <div class="enrollment-grid">
          <label>民警编号<input v-model="officerIdInput" :disabled="busy || recording" placeholder="例如 P-001" /></label>
          <label>民警姓名<input v-model="officerNameInput" :disabled="busy || recording" placeholder="请输入姓名" /></label>
          <button v-if="!recording" class="primary" :disabled="busy || !officerIdInput.trim() || !officerNameInput.trim()" @click="beginSample">开始添加新样本</button>
          <button v-else class="danger" :disabled="busy" @click="finalizeSample(false)">提前停止并保存样本</button>
        </div>
        <div v-if="recording" class="capture-progress" aria-live="polite"><div><strong>有效语音 {{ formatVoiceprintDuration(usableSpeechMs) }} / {{ formatVoiceprintDuration(requiredUsableSpeechMs) }}</strong><span>总采集 {{ formatVoiceprintDuration(capturedDurationMs) }}</span></div><div class="progress-track" role="progressbar" aria-label="民警有效语音采集进度" :aria-valuemin="0" :aria-valuemax="100" :aria-valuenow="progressPercent"><i :style="{ width: `${progressPercent}%` }"></i></div></div>
      </section></div></Teleport>
    </div>
    <aside class="library-sidebar" aria-label="声纹登记说明">
      <section class="library-card"><h3>采集要求</h3><ul><li>有效语音累计达到目标时长后自动完成登记</li><li>保持环境安静，避免他人说话</li><li>以正常语速与音量朗读，不要刻意变声</li><li>未达标时可继续自然说话</li></ul></section>
      <section class="library-card"><h3>跨案件复用</h3><p>民警声纹登记一次即可跨案件复用。新建询问时可直接选择已有档案，无需重复采集。</p><p>每次补录新增独立样本，案件绑定后保留当时的声纹版本。</p></section>
      <section class="library-card"><h3>样本管理</h3><p>选择民警后查看样本明细。停用样本会重建聚合声纹；停用民警档案后，该档案不再供新案件选用。</p><p>声纹用于说话人区分。</p></section>
    </aside>
  </section>
</template>

<style scoped>
.officer-library { display:grid; grid-template-columns:minmax(0,1fr) 300px; align-items:start; gap:26px; color:var(--primary-700); font-size:15px; max-width:1920px; margin:0 auto; }
.library-main { display:grid; gap:20px; min-width:0; }
.library-header { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:6px 0 2px; }
.library-header h2 { margin:0 0 12px; font-size:26px; color:var(--navy-900); }
.library-header p { margin:0; color:var(--ink-400); font-size:14px; line-height:1.8; }
.library-header button { flex-shrink:0; }
.library-actions { display:flex; align-items:center; gap:14px; }.library-actions input { max-width:240px; }
.library-card { border-radius:13px; background:var(--surface); overflow:hidden; }
h3 { margin:0; font-size:17px; color:var(--primary-700); }
button,input { font:inherit; }
button { min-height:44px; border:1px solid var(--line-300); border-radius:8px; padding:0 18px; background:var(--surface); color:var(--primary-600); font-size:15px; font-weight:600; cursor:pointer; }
button.primary { min-height:50px; border-color:var(--primary-600); background:var(--primary-600); color:var(--surface); }
button.danger { color:var(--danger-600); border-color:var(--danger-700); }
button:disabled,input:disabled { opacity:.55; cursor:not-allowed; }
button:focus-visible,input:focus-visible,summary:focus-visible { outline:3px solid var(--primary-500); outline-offset:3px; }
input { min-width:0; width:100%; min-height:44px; box-sizing:border-box; border:1px solid var(--line-300); border-radius:8px; padding:0 13px; background:var(--surface-sunken); color:var(--primary-700); }
.card-heading { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:20px 24px; }
.card-heading > span { color:var(--ink-400); font-size:13px; }
.table-scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; text-align:left; font-size:14px; }
th { background:var(--surface-sunken); color:var(--ink-400); font-weight:600; font-size:13px; white-space:nowrap; padding:16px 24px; }
td { padding:18px 24px; color:var(--ink-500); border-bottom:1px solid var(--primary-100); line-height:1.6; }
tbody tr:last-child td { border-bottom:0; }
.profiles-table tr.selected td { background:var(--surface-sunken); }
.profile-select { display:grid; gap:4px; text-align:left; border:0; background:transparent; padding:0; color:var(--primary-700); min-width:76px; }
.profile-select small { color:var(--ink-400); font-weight:400; font-size:12px; }
.status-chip { display:inline-flex; align-items:center; border-radius:20px; padding:4px 12px; color:var(--success-700); background:var(--success-100); font-size:13px; white-space:nowrap; }
.status-chip.inactive { color:var(--ink-400); background:var(--primary-100); }
.card-note,.detail-footer p { margin:0; color:var(--ink-400); font-size:13px; line-height:1.8; }
.card-note { padding:14px 24px; background:var(--surface-sunken); }
.sample-id { max-width:220px; overflow-wrap:anywhere; font-size:13px; }
.quality-label { color:var(--warning-600); font-weight:600; }.quality-label.good { color:var(--success-700); }
.samples-table tr.inactive { background:var(--surface-sunken); }.disabled-reason { color:var(--ink-400); font-size:13px; }
.sample-metadata summary { color:var(--primary-600); cursor:pointer; white-space:nowrap; }
dl { display:grid; gap:8px; margin:12px 0 0; font-size:13px; }dt { color:var(--ink-400); }dd { margin:2px 0 0; overflow-wrap:anywhere; }
.detail-footer { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:16px 24px; border-top:1px solid var(--primary-100); }
.detail-actions { display:flex; flex-wrap:wrap; gap:10px; flex-shrink:0; }
.voice-enrollment-overlay { position:fixed; inset:0; z-index:1000; display:flex; align-items:center; justify-content:center; padding:24px 24px calc(24px + var(--osk-height, 0px)); background:rgba(16,34,58,.5); box-sizing:border-box; color:var(--primary-700); font:15px 'Microsoft YaHei',sans-serif; }
.voice-enrollment-overlay .sample-enrollment-card { width:min(860px,100%); max-height:calc(100dvh - var(--osk-height, 0px) - 48px); overflow:auto; box-shadow:0 20px 70px rgba(10,25,45,.2); }
.voice-enrollment-overlay .enrollment-grid { grid-template-columns:1fr 1fr; }.voice-enrollment-overlay .enrollment-grid > button { grid-column:1 / -1; margin-top:6px; }.voice-enrollment-overlay .notice { margin-top:18px; }.close-enrollment { min-height:40px; }
.sample-enrollment-card { padding:24px; scroll-margin:24px; }.sample-enrollment-card .card-heading { padding:0; }
.enrollment-steps { margin:16px 0 8px; color:var(--primary-600); font-size:14px; font-weight:600; }.enrollment-hint { color:var(--ink-400); font-size:13px; margin:0; line-height:1.8; }
.enrollment-grid { display:grid; grid-template-columns:1fr 1fr auto; gap:18px; align-items:end; margin-top:20px; }.enrollment-grid label { display:grid; gap:9px; font-size:14px; color:var(--ink-400); }
.recording-chip { color:var(--warning-600) !important; }.capture-progress { margin-top:22px; padding:18px; background:var(--surface-sunken); border-radius:8px; }.capture-progress > div:first-child { display:flex; justify-content:space-between; gap:14px; font-size:14px; }.capture-progress span { color:var(--ink-400); }
.progress-track { margin-top:14px; height:12px; overflow:hidden; border-radius:20px; background:var(--primary-100); }.progress-track i { display:block; height:100%; background:var(--primary-600); transition:width .25s; }
.library-sidebar { display:grid; gap:20px; }.library-sidebar .library-card { padding:24px; }.library-sidebar h3 { margin-bottom:14px; font-size:16px; }.library-sidebar p,.library-sidebar ul { margin:0; color:var(--ink-400); font-size:14px; line-height:1.9; }.library-sidebar p + p { margin-top:14px; }.library-sidebar ul { padding-left:18px; }.library-sidebar li + li { margin-top:7px; }
.notice { padding:14px 18px; border-radius:8px; font-size:14px; line-height:1.7; }.notice.error { background:var(--danger-100); color:var(--danger-600); }.notice.success { background:var(--success-100); color:var(--success-700); }.empty-state { padding:36px 24px; text-align:center; color:var(--ink-400); font-size:14px; }
@media(max-width:1480px) { .officer-library { grid-template-columns:minmax(0,1fr) 260px; gap:18px; }th,td { padding:14px 16px; }.library-sidebar .library-card { padding:20px; } }
@media(max-width:1150px) { .officer-library { grid-template-columns:1fr; }.library-sidebar { grid-template-columns:repeat(3,minmax(0,1fr)); }.enrollment-grid { grid-template-columns:1fr 1fr; }.enrollment-grid button { grid-column:1 / -1; } }
@media(max-width:720px) { .library-header,.card-heading,.detail-footer { align-items:flex-start; flex-direction:column; }.library-sidebar,.enrollment-grid { grid-template-columns:1fr; }.library-actions { width:100%; flex-wrap:wrap; }.library-actions input { max-width:none; }.profiles-table { min-width:760px; }.samples-table { min-width:800px; }.capture-progress > div:first-child { flex-direction:column; } }
</style>
