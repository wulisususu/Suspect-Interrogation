<script setup lang="ts">
/**
 * 录音查看（真实功能，替代 P27 占位）
 *
 * 通道①：按题/片段的分段录音，可回听并对应转写；
 * 通道②：全程原始文件——每次「开始/继续询问 → 暂停/结束询问」一条连续录音，
 *        只做保存，调阅须管理员 + 填写原因并留痕。
 * 所有音频请求都带会话 Cookie，后端会写访问审计。
 */
import { computed, onMounted, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { fetchCases } from '../api/interrogation'
import {
  fetchCaseRecordings,
  originalAudioUrl,
  questionAudioUrl,
  segmentAudioUrl,
  updateRecordingOptions,
  type CaseRecordings,
  type RecordingOriginal,
  type RecordingQuestion,
  type RecordingSegment,
  type RecordingSegmentGap,
} from '../api/recordings'
import { fetchAuthSession, type AuthSession } from '../api/officers'
import type { CaseSummary } from '../types/interrogation'

const emit = defineEmits<{ login: [] }>()

const props = defineProps<{ caseId?: string }>()

type Gate = 'loading' | 'unconfigured' | 'unauthenticated' | 'ready' | 'error'

const gate = ref<Gate>('loading')
const session = ref<AuthSession | null>(null)
const cases = ref<CaseSummary[]>([])
const caseId = ref('')
const recordings = ref<CaseRecordings | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')
const playerUrl = ref('')
const playerTitle = ref('')
const reasonOpen = ref(false)
const reasonText = ref('核对录音')
const pendingOriginal = ref<RecordingOriginal | null>(null)
const pendingSegment = ref<RecordingSegment | null>(null)

const isAdmin = computed(() => Boolean(session.value?.officer?.isAdmin))
const questions = computed(() => recordings.value?.questions ?? [])
const originals = computed(() => recordings.value?.originals ?? [])
const segments = computed(() => recordings.value?.segments ?? [])
/** 全程录音上线前的案件没有询问段，只保留按次采集的原始文件。 */
const legacyOriginals = computed(() => !segments.value.length)
const SEGMENT_STATUS: Record<string, string> = { RECORDING: '录音中', CLOSING: '保存中', COMPLETE: '已保存', EMPTY: '无音频' }
const GAP_REASON: Record<string, string> = { BROWSER_RESTARTED: '页面刷新或重开', BROWSER_BUFFER_DROPPED: '断网过久、缓存溢出' }

async function boot() {
  gate.value = 'loading'
  error.value = ''
  try {
    const current = await fetchAuthSession()
    session.value = current
    if (!current.configured) {
      gate.value = 'unconfigured'
      return
    }
    if (!current.authenticated || current.locked) {
      gate.value = 'unauthenticated'
      return
    }
    gate.value = 'ready'
    await loadCases()
  } catch (err) {
    gate.value = 'error'
    error.value = err instanceof Error ? err.message : '录音数据读取失败'
  }
}

async function loadCases() {
  cases.value = await fetchCases(60)
  if (caseId.value) return
  // 从案件详情跳进来时预选该案件；否则退回第一条。
  const preferred = props.caseId && cases.value.some((item) => item.id === props.caseId) ? props.caseId : cases.value[0]?.id
  if (preferred) await selectCase(preferred)
}

async function selectCase(next: string) {
  caseId.value = next
  playerUrl.value = ''
  playerTitle.value = ''
  await loadRecordings()
}

async function loadRecordings() {
  if (!caseId.value) return
  loading.value = true
  error.value = ''
  try {
    recordings.value = await fetchCaseRecordings(caseId.value)
  } catch (err) {
    recordings.value = null
    error.value = err instanceof Error ? err.message : '本案录音读取失败'
  } finally {
    loading.value = false
  }
}

async function toggleFullRecording() {
  if (!recordings.value) return
  busy.value = true
  error.value = ''
  try {
    await updateRecordingOptions(recordings.value.caseId, !recordings.value.fullRecordingEnabled)
    message.value = recordings.value.fullRecordingEnabled ? '已关闭全程录音' : '已开启全程录音'
    await loadRecordings()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '全程录音开关保存失败'
  } finally {
    busy.value = false
  }
}

function playQuestion(row: RecordingQuestion) {
  if (!recordings.value) return
  const url = questionAudioUrl(recordings.value, row)
  if (!url) return
  playerUrl.value = url
  playerTitle.value = `通道① · 第 ${row.questionNumber ?? '—'} 题 · ${row.durationMs} ms`
}

function askOriginal(row: RecordingOriginal) {
  pendingSegment.value = null
  pendingOriginal.value = row
  reasonText.value = '核对录音'
  reasonOpen.value = true
}

function askSegment(row: RecordingSegment) {
  pendingOriginal.value = null
  pendingSegment.value = row
  reasonText.value = '核对录音'
  reasonOpen.value = true
}

function confirmOriginal() {
  const reason = reasonText.value.trim()
  const segment = pendingSegment.value
  const row = pendingOriginal.value
  if (!reason || (!segment && !row)) return
  if (segment) {
    playerUrl.value = segmentAudioUrl(caseId.value, segment.segmentId, reason)
    playerTitle.value = `通道② · 第 ${segment.ordinal} 次询问 · ${fmtDuration(segment.durationMs)}`
  } else if (row) {
    playerUrl.value = originalAudioUrl(caseId.value, row.captureSessionId, reason)
    playerTitle.value = `通道② · ${row.filename}`
  }
  reasonOpen.value = false
  pendingOriginal.value = null
  pendingSegment.value = null
  message.value = '已发起调阅，访问已记入审计'
}

function fmt(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function fmtTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN', { hour12: false })
}

function fmtDuration(ms: number) {
  const total = Math.round(ms / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const mmss = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return hours ? `${hours}:${mmss}` : mmss
}

function gapText(gap: RecordingSegmentGap) {
  const lost = gap.missingMs === null ? '时长未知' : `约 ${Math.max(1, Math.round(gap.missingMs / 1000))} 秒`
  return `${fmtDuration(gap.atMs)} 处缺 ${lost}（${GAP_REASON[gap.reason] ?? gap.reason}）`
}

function fmtSize(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

onMounted(boot)
</script>

<template>
  <section class="recording-admin">
    <header class="page-head">
      <div>
        <h1>录音查看 · 双通道双文件</h1>
        <p>通道①问答分段录音可回听、对应转写；通道②每次询问（开始/继续 → 暂停/结束）一条连续全程录音，作原始文件只做保存</p>
      </div>
      <button type="button" class="ghost" @click="boot">刷新</button>
    </header>

    <p v-if="error" class="page-error" role="alert">{{ error }}</p>
    <p v-if="message" class="page-ok" role="status">{{ message }}</p>

    <section v-if="gate === 'loading'" class="page-note">正在读取录音数据…</section>

    <section v-else-if="gate === 'unconfigured'" class="page-note">
      <strong>尚未配置民警名录</strong>
      <p>录音调阅需要民警身份。请部署人员在板端初始化管理员账号后再使用。</p>
    </section>

    <section v-else-if="gate === 'unauthenticated'" class="page-note">
      <strong>需要民警身份验证</strong>
      <p>录音属证据材料，调阅必须先验证身份；全程原始录音还需要管理员授权。</p>
      <button type="button" class="primary" @click="emit('login')">前往验证</button>
    </section>

    <section v-else-if="gate === 'error'" class="page-note">
      <strong>读取失败</strong>
      <p>{{ error }}</p>
      <button type="button" class="ghost" @click="boot">重试</button>
    </section>

    <template v-else>
      <div class="toolbar">
        <label>案件
          <select :value="caseId" @change="selectCase(($event.target as HTMLSelectElement).value)">
            <option v-if="!cases.length" value="">暂无可选案件</option>
            <option v-for="item in cases" :key="item.id" :value="item.id">
              {{ item.id }} · {{ item.suspectName }} · {{ fmt(item.createdAt) }}
            </option>
          </select>
        </label>
        <label v-if="recordings" class="switch">
          <input type="checkbox" :checked="recordings.fullRecordingEnabled" :disabled="busy" @change="toggleFullRecording" />
          <span>开启全程录音（下次开始/继续询问生效，录音过程中不可改）</span>
        </label>
      </div>

      <EmptyState v-if="!cases.length" kind="empty" title="还没有案件" description="先在大厅新建笔录，录音会随采集自动归档。" />
      <section v-else-if="loading" class="page-note">正在读取本案录音…</section>

      <div v-else-if="recordings" class="panes">
        <article class="pane">
          <header>
            <h2>通道① 问答分段录音（随题回听 · 对应转写）</h2>
            <span class="count">{{ questions.length }} 段</span>
          </header>
          <div class="pane-body">
            <EmptyState v-if="!questions.length" kind="empty" title="还没有分段录音" description="开始询问并按题作答后，这里会出现可回听的分段。" />
            <table v-else class="data-table">
            <thead><tr><th>题号</th><th>题目</th><th>时长</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in questions" :key="`${row.questionId}-${row.captureSessionId}-${row.fragmentId ?? ''}`">
                <td>{{ row.questionNumber ?? '—' }}</td>
                <td>
                  <strong>{{ row.question }}</strong>
                  <small v-if="!row.questionActive">（题目已停用）</small>
                </td>
                <td>{{ row.durationMs }} ms</td>
                <td>{{ row.available ? '可回听' : '存档未就绪' }}</td>
                <td>
                  <button type="button" class="link" :disabled="!row.available" @click="playQuestion(row)">播放</button>
                </td>
              </tr>
            </tbody>
          </table>
          </div>
        </article>

        <article class="pane">
          <header>
            <h2>通道② 全程录音（原始文件）</h2>
            <span class="count">{{ legacyOriginals ? originals.length : segments.length }} 个</span>
          </header>
          <p class="note">每次点「开始询问 / 继续询问」起录，点「暂停询问 / 结束询问」整段保存为一个文件；不参与转写、不拆分、不修改，用于事后核对与防翻供。</p>
          <div class="pane-body">
            <ul v-if="segments.length" class="original-list">
              <li v-for="row in segments" :key="row.segmentId" class="segment-item">
                <div class="original-head">
                  <strong>第 {{ row.ordinal }} 次询问</strong>
                  <span class="segment-status" :class="`is-${row.status.toLowerCase()}`">{{ SEGMENT_STATUS[row.status] ?? row.status }}</span>
                </div>
                <p>{{ fmt(row.startedAt) }} – {{ row.endedAt ? fmtTime(row.endedAt) : '进行中' }} · 录音 {{ fmtDuration(row.durationMs) }}<template v-if="row.sizeBytes"> · {{ fmtSize(row.sizeBytes) }}</template></p>
                <p v-if="row.sha256" class="digest">sha256 {{ row.sha256.slice(0, 16) }}…</p>
                <p v-if="row.status === 'EMPTY'" class="segment-warn">这段询问没有收到任何音频（麦克风未开启或浏览器未连上）。</p>
                <p v-if="row.gaps.length" class="segment-warn">中断 {{ row.gaps.length }} 处：{{ row.gaps.map(gapText).join('；') }}</p>
                <p v-if="row.status === 'COMPLETE' && !row.tailConfirmed" class="segment-warn">结尾未经浏览器确认（暂停时连接中断），已由服务端按已收到的音频保存。</p>
                <button
                  v-if="row.available"
                  type="button"
                  class="ghost small"
                  :disabled="!isAdmin"
                  :title="isAdmin ? '' : '调阅全程原始录音需要管理员授权'"
                  @click="askSegment(row)"
                >调阅全程录音（需授权 · 留痕）</button>
              </li>
            </ul>
            <EmptyState v-else-if="!originals.length" kind="empty" title="还没有全程录音" description="开启全程录音后，每次开始/继续询问到暂停询问会生成一个完整文件。" />
            <ul v-else class="original-list">
              <li v-for="row in originals" :key="row.captureSessionId">
                <div class="original-head">
                  <strong>{{ row.filename }}</strong>
                  <span>{{ fmtSize(row.sizeBytes) }}</span>
                </div>
                <p>{{ row.durationMs }} ms · {{ fmt(row.startedAt) }}</p>
                <p class="digest">sha256 {{ row.sha256.slice(0, 16) }}…</p>
                <button
                  type="button"
                  class="ghost small"
                  :disabled="!isAdmin"
                  :title="isAdmin ? '' : '调阅全程原始录音需要管理员授权'"
                  @click="askOriginal(row)"
                >调阅全程录音（需授权 · 留痕）</button>
              </li>
            </ul>
          </div>
        </article>
      </div>

      <section v-if="playerUrl" class="player">
        <header>
          <strong>{{ playerTitle }}</strong>
          <button type="button" class="link" @click="playerUrl = ''">关闭</button>
        </header>
        <audio :src="playerUrl" controls preload="none" />
      </section>
    </template>

    <div v-if="reasonOpen" class="reason-modal" role="dialog" aria-modal="true" aria-label="填写调阅原因">
      <section>
        <h2>调阅全程原始录音</h2>
        <p>本次调阅会记入审计：操作人、原因、录音编号与文件校验值。原因必填。</p>
        <input v-model="reasonText" maxlength="1000" placeholder="例如：核对笔录时间与录音是否一致" />
        <footer>
          <button type="button" class="ghost" @click="reasonOpen = false">取消</button>
          <button type="button" class="primary" :disabled="!reasonText.trim()" @click="confirmOriginal">确认调阅</button>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.recording-admin { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; height: 100%; min-height: 0; overflow: hidden; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); flex: 0 0 auto; }
.page-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.page-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-note { display: flex; flex-direction: column; gap: var(--space-2); align-items: flex-start; padding: var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); color: var(--ink-600); font-size: var(--text-sm); flex: 0 0 auto; }
.page-note strong { color: var(--ink-900); }
.page-note p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); flex: 0 0 auto; }
.page-ok { margin: 0; color: var(--success-700); font-size: var(--text-xs); flex: 0 0 auto; }
.toolbar { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--space-4); flex: 0 0 auto; }
.toolbar label { display: flex; flex-direction: column; gap: 4px; color: var(--ink-500); font-size: var(--text-xs); }
.toolbar select { min-width: 320px; min-height: 40px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-800); font-size: var(--text-sm); }
.switch { flex-direction: row !important; align-items: center; gap: var(--space-2); color: var(--ink-600); }
.panes { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: var(--space-4); align-items: stretch; flex: 1 1 auto; min-height: 0; overflow: hidden; }
.pane { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); min-height: 0; overflow: hidden; }
.pane header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); flex: 0 0 auto; }
.pane h2 { margin: 0; color: var(--ink-800); font-size: var(--text-base); }
.count { color: var(--ink-400); font-size: var(--text-xs); }
.note { margin: 0; color: var(--ink-500); font-size: var(--text-xs); flex: 0 0 auto; }
.pane-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { padding: var(--space-2); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); text-align: left; }
.data-table td { padding: var(--space-2); border-top: 1px solid var(--line-200); color: var(--ink-700); font-size: var(--text-sm); vertical-align: top; }
.data-table small { color: var(--ink-400); font-size: var(--text-xs); }
.original-list { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.original-list li { display: flex; flex-direction: column; gap: 4px; padding: var(--space-3); border: 1px solid var(--line-200); border-radius: var(--radius-md); background: var(--surface-sunken); }
.original-head { display: flex; justify-content: space-between; gap: var(--space-2); color: var(--ink-800); font-size: var(--text-sm); }
.original-list p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.digest { word-break: break-all; }
.segment-status { color: var(--ink-500); font-size: var(--text-xs); }
.segment-status.is-recording { color: var(--danger-600); }
.segment-status.is-complete { color: var(--success-700); }
.segment-status.is-empty, .segment-warn { color: var(--warning-700); }
.player { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); flex: 0 0 auto; }
.player header { display: flex; align-items: center; justify-content: space-between; }
.player strong { color: var(--ink-800); font-size: var(--text-sm); }
.player audio { width: 100%; }
.link { border: 0; background: transparent; color: var(--primary-700); font-size: var(--text-xs); cursor: pointer; }
.link:disabled { color: var(--ink-400); cursor: default; }
.primary, .ghost { min-height: 38px; padding: 0 var(--space-4); border-radius: var(--radius-md); font-size: var(--text-sm); cursor: pointer; }
.primary { border: 0; background: var(--primary-600); color: var(--surface); }
.ghost { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.ghost.small { min-height: 32px; align-self: flex-start; font-size: var(--text-xs); }
.primary:disabled, .ghost:disabled { opacity: 0.6; cursor: default; }
.reason-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--space-5); background: rgba(22, 38, 63, 0.72); }
.reason-modal section { display: flex; flex-direction: column; gap: var(--space-3); width: min(520px, 100%); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.reason-modal h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.reason-modal p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.reason-modal input { min-height: 42px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); font-size: var(--text-sm); }
.reason-modal footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
@media (max-width: 1200px) { .panes { grid-template-columns: 1fr; grid-auto-rows: minmax(0, 1fr); } }
</style>
