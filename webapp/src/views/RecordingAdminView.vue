<script setup lang="ts">
/**
 * 录音查看（真实功能，替代 P27 占位）
 *
 * 通道①：按题/片段的分段录音，可回听并对应转写；
 * 通道②：全程原始文件，只做保存，调阅须管理员 + 填写原因并留痕。
 * 所有音频请求都带会话 Cookie，后端会写访问审计。
 */
import { computed, onMounted, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { fetchCases } from '../api/interrogation'
import {
  fetchCaseRecordings,
  originalAudioUrl,
  questionAudioUrl,
  updateRecordingOptions,
  type CaseRecordings,
  type RecordingOriginal,
  type RecordingQuestion,
} from '../api/recordings'
import { fetchAuthSession, type AuthSession } from '../api/officers'
import type { CaseSummary } from '../types/interrogation'

const emit = defineEmits<{ login: [] }>()

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

const isAdmin = computed(() => Boolean(session.value?.officer?.isAdmin))
const questions = computed(() => recordings.value?.questions ?? [])
const originals = computed(() => recordings.value?.originals ?? [])

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
  if (!caseId.value && cases.value.length) {
    await selectCase(cases.value[0]!.id)
  }
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
  pendingOriginal.value = row
  reasonText.value = '核对录音'
  reasonOpen.value = true
}

function confirmOriginal() {
  const row = pendingOriginal.value
  if (!row || !reasonText.value.trim()) return
  playerUrl.value = originalAudioUrl(caseId.value, row.captureSessionId, reasonText.value.trim())
  playerTitle.value = `通道② · ${row.filename}`
  reasonOpen.value = false
  pendingOriginal.value = null
  message.value = '已发起调阅，访问已记入审计'
}

function fmt(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
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
        <p>通道①问答分段录音可回听、对应转写；通道②全程录音作原始文件只做保存</p>
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
          <span>开启全程录音（下次采集生效，采集过程中不可改）</span>
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
        </article>

        <article class="pane">
          <header>
            <h2>通道② 全程录音（原始文件）</h2>
            <span class="count">{{ originals.length }} 个</span>
          </header>
          <p class="note">全程录音作为原始文件只做保存，不参与转写、不拆分、不修改；用于事后核对与防翻供。</p>
          <EmptyState v-if="!originals.length" kind="empty" title="还没有全程原始录音" description="开启全程录音后的采集才会生成；关闭期间的采集只保留分段。" />
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
        <p>本次调阅会记入审计：操作人、原因、采集编号与文件校验值。原因必填。</p>
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
.recording-admin { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.page-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.page-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-note { display: flex; flex-direction: column; gap: var(--space-2); align-items: flex-start; padding: var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); color: var(--ink-600); font-size: var(--text-sm); }
.page-note strong { color: var(--ink-900); }
.page-note p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); }
.page-ok { margin: 0; color: var(--success-700); font-size: var(--text-xs); }
.toolbar { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--space-4); }
.toolbar label { display: flex; flex-direction: column; gap: 4px; color: var(--ink-500); font-size: var(--text-xs); }
.toolbar select { min-width: 320px; min-height: 40px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-800); font-size: var(--text-sm); }
.switch { flex-direction: row !important; align-items: center; gap: var(--space-2); color: var(--ink-600); }
.panes { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.pane { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
.pane header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.pane h2 { margin: 0; color: var(--ink-800); font-size: var(--text-base); }
.count { color: var(--ink-400); font-size: var(--text-xs); }
.note { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { padding: var(--space-2); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); text-align: left; }
.data-table td { padding: var(--space-2); border-top: 1px solid var(--line-200); color: var(--ink-700); font-size: var(--text-sm); vertical-align: top; }
.data-table small { color: var(--ink-400); font-size: var(--text-xs); }
.original-list { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.original-list li { display: flex; flex-direction: column; gap: 4px; padding: var(--space-3); border: 1px solid var(--line-200); border-radius: var(--radius-md); background: var(--surface-sunken); }
.original-head { display: flex; justify-content: space-between; gap: var(--space-2); color: var(--ink-800); font-size: var(--text-sm); }
.original-list p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.digest { word-break: break-all; }
.player { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
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
@media (max-width: 1200px) { .panes { grid-template-columns: 1fr; } }
</style>
