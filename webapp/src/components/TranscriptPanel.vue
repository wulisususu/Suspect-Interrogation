<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { AlertTriangle, Check, Mic, Square, Trash2 } from '@lucide/vue'
import { temporarySpeakerPresentation } from './VoiceprintPreparationPanel.vue'
import type { AsrCaptureStatus, TemporaryAsrFragment, TemporaryAsrSpeaker, TranscriptMessage } from '../types/interrogation'
import AsrWorkflowStatus from './AsrWorkflowStatus.vue'

const props = defineProps<{
  messages: TranscriptMessage[]
  streaming: boolean
  canRecord: boolean
  nativeCaptureAvailable: boolean
  capture: AsrCaptureStatus
  captureBusy: boolean
  captureElapsedMs: number
  selectedFragmentIds: string[]
  error?: string
  fragmentHistory?: (fragmentId: string) => TemporaryAsrFragment[]
}>()
const emit = defineEmits<{
  send: [text: string]
  edit: [messageId: string, text: string]
  mark: [messageId: string]
  versions: [messageId?: string]
  markLatest: []
  captureStart: []
  captureStop: []
  updateFragment: [fragmentId: string, editedText: string, speaker: TemporaryAsrSpeaker]
  confirmFragment: [fragmentId: string]
  discardFragment: [fragmentId: string]
  toggleFragment: [fragmentId: string]
  confirmSelected: []
}>()

const draft = ref('')
const scroller = ref<HTMLElement | null>(null)
const composerInput = ref<HTMLTextAreaElement | null>(null)
const editingId = ref('')
const editingText = ref('')

watch(
  () => props.messages.map((item) => item.text).join('|'),
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  },
)

function submit() {
  const text = draft.value.trim()
  if (!text || props.streaming || !props.canRecord) return
  emit('send', text)
  draft.value = ''
}

function resizeComposer() {
  const input = composerInput.value
  if (!input) return
  input.style.height = 'auto'
  const style = getComputedStyle(input)
  const lineHeight = Number.parseFloat(style.lineHeight)
  const chrome = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom)
    + Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth)
  const maxHeight = lineHeight * 5 + chrome
  input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`
  input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

watch(draft, async () => {
  await nextTick()
  resizeComposer()
})

function startEdit(message: TranscriptMessage) {
  editingId.value = message.id
  editingText.value = message.text
}

function saveEdit() {
  const text = editingText.value.trim()
  if (!editingId.value || !text) return
  emit('edit', editingId.value, text)
  editingId.value = ''
  editingText.value = ''
}

function formatElapsed(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

function formatTimestamp(value: number) {
  return formatElapsed(value)
}

function confidenceLabel(fragment: TemporaryAsrFragment) {
  return fragment.confidence == null ? '置信度不可用' : `置信度 ${Math.round(fragment.confidence * 100)}%`
}

function speakerPresentation(fragment: TemporaryAsrFragment) {
  return temporarySpeakerPresentation(fragment.speaker, fragment.speakerName)
}

function updateFragmentText(fragment: TemporaryAsrFragment, event: Event) {
  emit('updateFragment', fragment.id, (event.target as HTMLTextAreaElement).value, fragment.speaker)
}

function updateFragmentSpeaker(fragment: TemporaryAsrFragment, event: Event) {
  emit('updateFragment', fragment.id, fragment.editedText, (event.target as HTMLSelectElement).value as TemporaryAsrSpeaker)
}
</script>

<template>
  <section class="panel transcript-panel">
    <header class="panel-header">
      <strong>实时问答 / 审讯记录</strong>
      <div class="panel-actions">
        <button class="ghost-button" @click="$emit('markLatest')">标记最新矛盾</button>
        <button class="ghost-button" @click="$emit('versions')">查看版本</button>
      </div>
    </header>

    <div ref="scroller" class="transcript-list">
      <article
        v-for="message in messages"
        :key="message.id"
        class="qa-row"
        :data-speaker="message.speaker"
        :data-mark="message.mark || ''"
      >
        <div class="qa-index">
          {{ message.speaker === '民警' ? `Q${message.seq || ''}` : message.speaker === '嫌疑人' ? `A${message.seq || ''}` : 'AI' }}
        </div>
        <div class="qa-content">
          <div class="qa-toolbar">
            <strong>{{ message.speaker }}：</strong>
            <span v-if="message.mark === 'conflict'" class="record-mark conflict">存在矛盾</span>
            <div v-if="message.speaker !== 'AI'" class="message-actions">
              <button @click="startEdit(message)">编辑</button>
              <button @click="$emit('mark', message.id)">标记</button>
              <button @click="$emit('versions', message.id)">版本</button>
            </div>
          </div>

          <div v-if="editingId === message.id" class="inline-editor">
            <textarea v-model="editingText" />
            <div>
              <button class="primary-small" @click="saveEdit">保存修订</button>
              <button @click="editingId = ''">取消</button>
            </div>
          </div>
          <template v-else>
            <span>{{ message.text || (message.streaming ? '正在接收 SSE…' : '') }}</span>
            <span v-if="message.streaming" class="typing-dot">●</span>
          </template>
        </div>
      </article>
      <div v-if="error" class="error-box">{{ error }}</div>
      <div v-if="!messages.length" class="empty-box">暂无正式问答。开始审讯后发送第一条问题。</div>
    </div>

    <footer class="transcript-capture-footer">
      <AsrWorkflowStatus :capture="capture" />

      <div v-if="capture.partialText" class="asr-live-partial" aria-live="polite">
        <span>实时转写</span>
        <strong>{{ capture.partialText }}</strong>
      </div>

      <section v-if="capture.fragments.length" class="asr-fragment-area">
        <header>
          <span>待确认片段 {{ capture.fragments.length }}</span>
          <button
            class="fragment-batch-button"
            :disabled="!selectedFragmentIds.length"
            @click="$emit('confirmSelected')"
          >
            <Check :size="15" /> 批量确认 {{ selectedFragmentIds.length || '' }}
          </button>
        </header>
        <div class="asr-fragment-list">
          <article
            v-for="fragment in capture.fragments"
            :key="fragment.id"
            class="asr-fragment-row"
            :class="{ 'low-confidence': fragment.lowConfidence }"
          >
            <input
              type="checkbox"
              :checked="selectedFragmentIds.includes(fragment.id)"
              :aria-label="`选择片段 ${fragment.ordinal}`"
              @change="$emit('toggleFragment', fragment.id)"
            >
            <div class="fragment-main">
              <div class="fragment-meta">
                <strong>{{ speakerPresentation(fragment).label }}</strong>
                <span>{{ speakerPresentation(fragment).detail }}</span>
                <span>{{ formatTimestamp(fragment.startedAtMs) }} - {{ formatTimestamp(fragment.endedAtMs) }}</span>
                <span :class="{ warning: fragment.lowConfidence }">
                  <AlertTriangle v-if="fragment.lowConfidence" :size="14" />
                  {{ confidenceLabel(fragment) }}
                </span>
                <span>{{ fragment.voiceprintVerified ? '声纹已验证' : '身份未由声纹验证' }}</span>
              </div>
              <textarea
                :value="fragment.editedText"
                rows="1"
                aria-label="临时转写文本"
                @change="updateFragmentText(fragment, $event)"
              />
              <details
                v-if="(fragmentHistory?.(fragment.id) ?? []).some((history) => history.id !== fragment.id)"
                class="fragment-lineage"
              >
                <summary>查看原始转写与分析沿革</summary>
                <div v-for="history in (fragmentHistory?.(fragment.id) ?? [])" :key="history.id" class="fragment-lineage-row">
                  <strong>{{ history.state === 'SUPERSEDED' ? '原始转写' : '分析后片段' }}</strong>
                  <span>{{ history.rawText }}</span>
                </div>
              </details>
            </div>
            <select
              :value="fragment.speaker"
              aria-label="说话人"
              @change="updateFragmentSpeaker(fragment, $event)"
            >
              <option value="UNKNOWN">待确认</option>
              <option value="OFFICER_FALLBACK">民警（非嫌疑人规则）</option>
              <option value="INTERROGATOR">主审民警</option>
              <option value="RECORDER">记录民警</option>
              <option value="SUSPECT">嫌疑人</option>
            </select>
            <button
              class="fragment-icon-button confirm"
              title="确认并正式入库"
              aria-label="确认并正式入库"
              :disabled="!fragment.editedText.trim() || fragment.speaker === 'UNKNOWN' || fragment.state === 'SUPERSEDED'"
              @click="$emit('confirmFragment', fragment.id)"
            >
              <Check :size="17" />
            </button>
            <button
              class="fragment-icon-button discard"
              title="丢弃临时片段"
              aria-label="丢弃临时片段"
              @click="$emit('discardFragment', fragment.id)"
            >
              <Trash2 :size="17" />
            </button>
          </article>
        </div>
      </section>

      <div class="composer">
        <button
          class="capture-toggle"
          :class="{ active: capture.running }"
          :disabled="captureBusy || !canRecord || !nativeCaptureAvailable"
          :title="nativeCaptureAvailable ? (capture.running ? '停止连续录音' : '开始连续录音') : 'Linux 连续离线录音 Runtime 当前不可用'"
          :aria-label="capture.running ? '停止连续录音' : '开始连续录音'"
          @click="capture.running ? $emit('captureStop') : $emit('captureStart')"
        >
          <Square v-if="capture.running" :size="18" fill="currentColor" />
          <Mic v-else :size="19" />
          <span v-if="capture.running">{{ formatElapsed(captureElapsedMs) }}</span>
        </button>
        <textarea
          ref="composerInput"
          v-model="draft"
          rows="1"
          :placeholder="canRecord ? '输入审讯问题；Ctrl/⌘ + Enter 发送' : '请先开始审讯；暂停状态下不能新增正式问答'"
          :disabled="!canRecord"
          @keydown.ctrl.enter.prevent="submit"
          @keydown.meta.enter.prevent="submit"
        />
        <button class="primary-button" :disabled="!draft.trim() || streaming || !canRecord" @click="submit">
          {{ streaming ? 'AI 回复中…' : '发送并保存' }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.fragment-lineage {
  margin-top: 6px;
  padding: 6px 8px;
  border: 1px solid var(--line-300);
  border-radius: 7px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  font-size: 12px;
}

.fragment-lineage summary {
  cursor: pointer;
}

.fragment-lineage-row {
  display: flex;
  gap: 8px;
  padding-top: 5px;
}
</style>
