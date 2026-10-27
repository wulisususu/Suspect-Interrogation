<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import type { AsrCaptureStatus, TemporaryAsrFragment, TemporaryAsrSpeaker } from '../types/interrogation'
import type {
  FormalQAUnit,
  FormalQuestion,
  PendingFormalQuestion,
  PendingResolution,
  QAUnitResolution,
} from '../types/templateInterrogation'
import { dialoguePresentation, groupLiveDialogueFragments } from '../utils/templateInterrogation'
import { armDrop, clearDrop, pendingDrop } from '../composables/pendingDrop'
import AsrWorkflowStatus from './AsrWorkflowStatus.vue'
import RecorderWaveformCanvas from './RecorderWaveformCanvas.vue'

const props = defineProps<{
  caseId: string
  dialogue: TemporaryAsrFragment[]
  partialText: string
  pendingQuestions: PendingFormalQuestion[]
  qaUnits: FormalQAUnit[]
  questions: FormalQuestion[]
  suspectName?: string
  captureRunning: boolean
  captureStatus: AsrCaptureStatus
  fragmentHistory: (fragmentId: string) => TemporaryAsrFragment[]
  captureBusy: boolean
  captureAvailable: boolean
  captureElapsedMs: number
}>()

const emit = defineEmits<{
  captureToggle: []
  resolvePending: [pendingId: string, resolution: PendingResolution]
  resolveQaUnit: [qaUnitId: string, resolution: QAUnitResolution]
  rollbackQaUnit: [qaUnitId: string]
  correctFragment: [fragmentId: string, speaker: TemporaryAsrSpeaker, reason: string]
}>()

const transcriptFeed = ref<HTMLElement | null>(null)
const pinnedToBottom = ref(true)
const correctionSpeaker = ref<Record<string, TemporaryAsrSpeaker>>({})
const correctionReason = ref<Record<string, string>>({})
const livePreviewUnavailable = computed(() => ['MODEL_NOT_INSTALLED', 'ERROR'].includes(
  String(props.captureStatus.liveTranscriptStatus ?? '').toUpperCase(),
))
const livePreviewUnavailableMessage = computed(() => (
  props.captureStatus.liveTranscriptStatus === 'MODEL_NOT_INSTALLED'
    ? '实时转写模型未安装，最终文字仍会保存'
    : '实时转写暂不可用，最终文字仍会保存'
))
const qaReviewUnits = computed(() => props.qaUnits.filter((unit) => unit.status === 'NEEDS_REVIEW'))
const qaResolvedUnits = computed(() => props.qaUnits.filter((unit) => unit.status === 'APPLIED' || unit.status === 'IGNORED' || unit.status === 'ROLLED_BACK'))
const visibleDialogue = computed(() => groupLiveDialogueFragments(props.dialogue))
const recognitionFragments = computed(() => [...props.dialogue]
  .filter((item) => item.state !== 'DISCARDED' && item.state !== 'SUPERSEDED' && (item.editedText || item.rawText).trim())
  .sort((left, right) => left.startedAtMs - right.startedAtMs || left.ordinal - right.ordinal || left.id.localeCompare(right.id)))

const elapsed = computed(() => {
  const total = Math.floor(props.captureElapsedMs / 1000)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
})
const audioMeterSamples = computed(() => props.captureStatus.audioLevels?.slice(-240) ?? [])
const audioMeterSignal = computed(() => {
  if (!props.captureRunning) return 'STOPPED'
  if (!audioMeterSamples.value.length) return 'WAITING'
  const updatedAt = props.captureStatus.audioLevelUpdatedAt
  const captureStart = props.captureStatus.startedAt
  const now = captureStart == null ? Date.now() : captureStart + props.captureElapsedMs
  if (updatedAt == null || now - updatedAt > 1500) return 'STALE'
  return 'LIVE'
})

function formatTime(item: TemporaryAsrFragment) {
  if (!item.createdAt) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(item.createdAt))
}

function formatDate(value?: number | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value))
}

function speakerLabel(role?: TemporaryAsrSpeaker | null) {
  if (role === 'SUSPECT') return '嫌疑人'
  if (role === 'INTERROGATOR') return '主审民警'
  if (role === 'RECORDER') return '记录民警'
  if (role === 'OFFICER_FALLBACK') return '非嫌疑人 / 未确认民警'
  return '未知人员'
}

function recognitionNeedsReview(item: TemporaryAsrFragment) {
  return item.speaker === 'UNKNOWN'
    || item.speaker === 'OFFICER_FALLBACK'
    || item.speakerSource === 'PENDING_ANALYSIS'
    || item.lowConfidence
}

function recognitionStatusLabel(item: TemporaryAsrFragment) {
  if (item.speakerSource === 'PENDING_ANALYSIS') return '声纹分析中'
  if (recognitionNeedsReview(item)) return '待人工复核'
  return item.voiceprintVerified ? '声纹已匹配' : '已归属'
}

function speakerName(item: TemporaryAsrFragment) {
  const presentation = dialoguePresentation(item)
  if (item.speaker === 'SUSPECT') return props.suspectName || item.speakerName || presentation.badge
  return item.speakerName || presentation.badge
}

function pendingFor(fragmentId: string) {
  return props.pendingQuestions.find((item) => item.officerFragmentId === fragmentId && (item.status === 'PENDING' || item.status === 'DEFERRED'))
}

function candidateQuestions(pending: PendingFormalQuestion) {
  const ids = new Set(pending.candidateQuestionIds)
  return props.questions.filter((question) => ids.has(question.id))
}

function resolve(pending: PendingFormalQuestion, resolution: PendingResolution) {
  emit('resolvePending', pending.id, resolution)
}

const FORMAL_ANSWER_FRAGMENT_MIME = 'application/x-formal-answer-fragments'

function dialogueDropEntries(fragments: TemporaryAsrFragment[]) {
  const fragmentIds = fragments.map((item) => item.id)
  if (!fragmentIds.length) return []
  const text = fragments
    .map((item) => (item.editedText || item.rawText || '').trim())
    .join('')
  const entries = [
    { mime: FORMAL_ANSWER_FRAGMENT_MIME, data: JSON.stringify({ fragmentIds, text }) },
  ]
  const pending = pendingFor(fragmentIds[0])
  if (pending) {
    entries.push({
      mime: 'application/x-formal-pending-question',
      data: JSON.stringify({ pendingId: pending.id }),
    })
  }
  return entries
}

function startDialogueDrag(event: DragEvent, fragments: TemporaryAsrFragment[]) {
  if (!event.dataTransfer) return
  const entries = dialogueDropEntries(fragments)
  if (!entries.length) return
  event.dataTransfer.effectAllowed = 'copy'
  for (const entry of entries) event.dataTransfer.setData(entry.mime, entry.data)
}

/** 触摸屏点选：等价于「按下了拖动但还没松手」，之后点笔录栏位即放置。 */
function armDialogue(fragments: TemporaryAsrFragment[]) {
  const entries = dialogueDropEntries(fragments)
  if (entries.length) armDrop(entries, '对话片段')
}

function toggleDialogueSelection(fragments: TemporaryAsrFragment[]) {
  if (dialogueArmed(fragments)) {
    clearDrop()
    return
  }
  armDialogue(fragments)
}

function dialogueArmed(fragments: TemporaryAsrFragment[]) {
  const ids = fragments.map((item) => item.id)
  const payload = pendingDrop.value
  if (!ids.length || !payload) return false
  return payload.entries.some(
    (entry) => entry.mime === FORMAL_ANSWER_FRAGMENT_MIME && ids.every((id) => entry.data.includes(id)),
  )
}

function wholeQaDropEntries(unit: FormalQAUnit) {
  return [{ mime: 'application/x-formal-qa-unit', data: JSON.stringify({ qaUnitId: unit.id, mode: 'QA' }) }]
}

function answerQaDropEntries(unit: FormalQAUnit) {
  return [{ mime: 'application/x-formal-qa-unit', data: JSON.stringify({ qaUnitId: unit.id, mode: 'ANSWER' }) }]
}

function startQaDrag(event: DragEvent, payload: { qaUnitId: string; mode: 'QA' | 'ANSWER' }) {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-formal-qa-unit', JSON.stringify(payload))
}

function startWholeQaDrag(event: DragEvent, unit: FormalQAUnit) {
  startQaDrag(event, { qaUnitId: unit.id, mode: 'QA' })
}

function startAnswerDrag(event: DragEvent, unit: FormalQAUnit) {
  startQaDrag(event, { qaUnitId: unit.id, mode: 'ANSWER' })
}

function resolveQa(unit: FormalQAUnit, resolution: QAUnitResolution) {
  emit('resolveQaUnit', unit.id, resolution)
}

function rollbackQa(unit: FormalQAUnit) {
  if (unit.status !== 'APPLIED') return
  if (!window.confirm('仅回退本次正式笔录回答，问题和原始对话会保留。确定继续吗？')) return
  emit('rollbackQaUnit', unit.id)
}

function qaStatusLabel(unit: FormalQAUnit) {
  if (unit.status === 'IGNORED' || unit.classification === 'IGNORE') return '已忽略·仅原始对话'
  if (unit.status === 'NEEDS_REVIEW') return '待处理'
  if (unit.status === 'ROLLED_BACK') return '已回退·问题保留'
  if (unit.classification === 'MATCH_FIXED') return '已归档·固定模板'
  if (unit.classification === 'MATCH_EXISTING') return '已归档·已有问题'
  if (unit.classification === 'CREATE_LIVE_FROM_SPEECH') return '已新增·现场问题'
  return unit.status
}

function correctionRole(item: TemporaryAsrFragment): TemporaryAsrSpeaker {
  return correctionSpeaker.value[item.id] || item.speaker
}

function submitCorrection(item: TemporaryAsrFragment) {
  const reason = (correctionReason.value[item.id] || '').trim()
  if (!reason) return
  emit('correctFragment', item.id, correctionRole(item), reason)
}

function onFeedScroll() {
  const element = transcriptFeed.value
  if (!element) return
  pinnedToBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight <= 80
}

async function scrollToLatest(force = false) {
  await nextTick()
  const element = transcriptFeed.value
  if (!element || (!force && !pinnedToBottom.value)) return
  element.scrollTop = element.scrollHeight
  pinnedToBottom.value = true
}

watch(
  () => [visibleDialogue.value.map((turn) => turn.text).join(''), props.partialText],
  () => { void scrollToLatest() },
)

watch(() => props.caseId, () => {
  void scrollToLatest(true)
})

onMounted(() => {
  void scrollToLatest(true)
})
</script>

<template>
  <aside class="live-dialogue-panel">
    <header class="live-dialogue-header">
      <div>
        <span class="panel-kicker">原文 / 实时转写</span>
        <h2>实时语音对话</h2>
      </div>
      <div class="live-dialogue-actions">
        <div class="capture-control">
          <button
            class="capture-toggle"
            :class="{ active: captureRunning }"
            :disabled="captureBusy || !captureAvailable"
            @click="emit('captureToggle')"
        >
          <span class="record-dot"></span>
          {{ captureRunning ? `停止录音 ${elapsed}` : '开始录音' }}
        </button>
        </div>
      </div>
    </header>

    <div class="dialogue-zones">
      <div class="dialogue-upper-zones">
        <section class="dialogue-region waveform-region" aria-label="实时录音波形">
          <div class="region-heading">
            <strong>录音波形</strong>
            <span class="capture-meter-state">
              {{ audioMeterSignal === 'LIVE' ? '实时音频' : audioMeterSignal === 'STALE' ? '暂无新音频信号' : audioMeterSignal === 'WAITING' ? '等待音频输入' : '录音未进行' }}
            </span>
          </div>
          <div class="capture-meter-waveform" role="img" aria-label="实时麦克风输入振幅波形">
            <RecorderWaveformCanvas
              v-if="captureRunning && audioMeterSamples.length"
              :key="captureStatus.captureSessionId ?? 'active-capture'"
              :samples="audioMeterSamples"
            />
            <span v-else class="waveform-placeholder">{{ captureRunning ? '等待音频输入' : '开始录音后显示实时波形' }}</span>
          </div>
        </section>

        <section class="dialogue-region transcript-region" aria-label="实时转写文本">
          <header class="region-heading transcript-heading">
            <div>
              <strong>转写文本 · 第 1 步</strong>
              <AsrWorkflowStatus :capture="captureStatus" stage="transcription" />
            </div>
            <button v-if="!pinnedToBottom" class="latest-inline-button" @click="scrollToLatest(true)">↓ 最新消息</button>
          </header>
          <div ref="transcriptFeed" class="transcript-content" @scroll="onFeedScroll">
            <div v-if="!visibleDialogue.length && !partialText && !captureRunning" class="dialogue-empty">
              <strong>等待现场对话</strong>
              <p>原始转写会在这里连续显示。</p>
            </div>

            <p v-if="visibleDialogue.length || partialText || captureRunning" class="transcript-paragraph">
              <span
                v-for="turn in visibleDialogue"
                :key="turn.key"
                class="transcript-fragment"
                :class="{ selected: dialogueArmed(turn.fragments) }"
                :role="'button'"
                :tabindex="0"
                :aria-label="'选择这段转写并放入笔录'"
                :aria-pressed="dialogueArmed(turn.fragments)"
                :data-fragment-id="turn.primary.id"
                :draggable="true"
                @dragstart="startDialogueDrag($event, turn.fragments)"
                @click.stop="armDialogue(turn.fragments)"
                @keydown.enter.prevent="armDialogue(turn.fragments)"
                @keydown.space.prevent="armDialogue(turn.fragments)"
              >{{ turn.text }}</span><span v-if="captureRunning" class="transcript-live-partial" :class="{ idle: !partialText }" aria-live="polite">{{ partialText || (livePreviewUnavailable ? livePreviewUnavailableMessage : '等待识别文字…请说话') }}</span>
            </p>

          </div>
        </section>
      </div>

      <section class="dialogue-region recognition-region" aria-label="说话人识别结果">
        <header class="region-heading recognition-heading">
          <div>
            <strong>说话人识别 · 第 2 步</strong>
            <AsrWorkflowStatus :capture="captureStatus" stage="speaker" />
          </div>
          <span class="recognition-count">{{ recognitionFragments.length }} 段</span>
        </header>
        <div class="recognition-list">
          <details v-if="qaReviewUnits.length || qaResolvedUnits.length" class="qa-review-rail" aria-label="正式笔录归档处理">
            <summary>正式笔录归档处理（{{ qaReviewUnits.length }} 项待处理）</summary>
            <article v-for="unit in qaReviewUnits" :key="unit.id" class="qa-review-card">
              <header><span class="qa-status-chip">待处理</span><small>{{ unit.reasonCode || 'NEEDS_REVIEW' }}</small></header>
              <p v-if="unit.rawQuestionText"><b>原始问：</b>{{ unit.rawQuestionText }}</p>
              <p v-if="unit.rawAnswerText"><b>原始答：</b>{{ unit.rawAnswerText }}</p>
              <p v-if="unit.aiSuggestedQuestionText" class="qa-suggestion"><b>AI 建议问：</b>{{ unit.aiSuggestedQuestionText }}</p>
              <p v-if="unit.aiSuggestedAnswerText" class="qa-suggestion"><b>AI 建议答：</b>{{ unit.aiSuggestedAnswerText }}</p>
              <div class="qa-review-actions">
                <button draggable="true" @dragstart="startWholeQaDrag($event, unit)" @click="armDrop(wholeQaDropEntries(unit), '整组问答')">拖动整组问答</button>
                <button v-if="unit.answerFragmentIds.length" draggable="true" @dragstart="startAnswerDrag($event, unit)" @click="armDrop(answerQaDropEntries(unit), '仅答案')">仅拖动答案</button>
                <button class="qa-ignore" @click="resolveQa(unit, { action: 'IGNORE' })">忽略</button>
              </div>
            </article>
            <div v-for="unit in qaResolvedUnits" :key="`status-${unit.id}`" class="qa-routing-status" :class="{ 'qa-status-muted': unit.status === 'IGNORED' || unit.status === 'ROLLED_BACK' || unit.classification === 'IGNORE' }">
              <span>{{ qaStatusLabel(unit) }}</span>
              <small v-if="unit.rawQuestionText">{{ unit.rawQuestionText }}</small>
              <button v-if="unit.status === 'APPLIED'" class="qa-rollback" @click="rollbackQa(unit)">回退本次匹配</button>
            </div>
          </details>
          <p v-if="!recognitionFragments.length" class="recognition-empty">
            {{ captureRunning ? '等待第 1 步产生文字片段' : '识别结果会显示在这里' }}
          </p>
          <article v-for="item in recognitionFragments" :key="item.id" class="recognition-entry">
            <div class="recognition-row">
              <time class="recognition-time">{{ formatTime(item) }}</time>
              <p class="recognition-excerpt">{{ (item.editedText || item.rawText).trim() }}</p>
              <span class="speaker-result-chip" :class="{ review: recognitionNeedsReview(item) }">{{ speakerName(item) }}</span>
              <span class="recognition-result-state" :class="{ review: recognitionNeedsReview(item) }">{{ recognitionStatusLabel(item) }}</span>
            </div>
            <div class="recognition-entry-actions">
              <button
                type="button"
                class="recognition-transfer-button"
                :class="{ selected: dialogueArmed([item]) }"
                :aria-pressed="dialogueArmed([item])"
                @click.stop="toggleDialogueSelection([item])"
              >{{ dialogueArmed([item]) ? '已选中' : '选择此段' }}</button>
            </div>

            <details v-if="fragmentHistory(item.id).some((history) => history.id !== item.id)" class="fragment-lineage">
              <summary>查看原始转写与说话人分析沿革</summary>
              <div v-for="history in fragmentHistory(item.id)" :key="history.id" class="fragment-lineage-row">
                <strong>{{ history.state === 'SUPERSEDED' ? '原始转写' : '分析后片段' }}</strong>
                <span>{{ history.rawText }}</span>
              </div>
            </details>

            <section v-if="pendingFor(item.id)" class="pending-resolution-card">
              <template v-if="pendingFor(item.id)?.matchStatus === 'UNMATCHED'">
                <p>未匹配正式笔录问题 · 可直接拖到左侧正式笔录指定位置</p>
                <div class="pending-actions">
                  <button class="primary" @click="resolve(pendingFor(item.id)!, { action: 'ADD' })">加入本案笔录</button>
                  <button @click="resolve(pendingFor(item.id)!, { action: 'IGNORE' })">忽略</button>
                </div>
              </template>
              <template v-else-if="pendingFor(item.id)?.matchStatus === 'AMBIGUOUS'">
                <p>可能对应多个正式问题，请人工确认</p>
                <div class="candidate-list">
                  <button
                    v-for="candidate in candidateQuestions(pendingFor(item.id)!)"
                    :key="candidate.id"
                    @click="resolve(pendingFor(item.id)!, { action: 'LINK', caseQuestionId: candidate.id, roundMode: 'NEW_ROUND' })"
                  >对应：{{ candidate.text }}</button>
                </div>
                <div class="pending-actions">
                  <button class="primary" @click="resolve(pendingFor(item.id)!, { action: 'ADD' })">新建本案问题</button>
                  <button @click="resolve(pendingFor(item.id)!, { action: 'IGNORE' })">忽略</button>
                </div>
              </template>
              <template v-else-if="pendingFor(item.id)?.matchStatus === 'MATCHED_EXISTING'">
                <p>该问题已在本案笔录中出现，请选择本次问答如何记录</p>
                <div class="pending-actions">
                  <button
                    v-if="pendingFor(item.id)!.candidateQuestionIds[0]"
                    class="primary"
                    @click="resolve(pendingFor(item.id)!, { action: 'LINK', caseQuestionId: pendingFor(item.id)!.candidateQuestionIds[0], roundMode: 'APPEND_EXISTING' })"
                  >追加到原回答</button>
                  <button
                    v-if="pendingFor(item.id)!.candidateQuestionIds[0]"
                    @click="resolve(pendingFor(item.id)!, { action: 'LINK', caseQuestionId: pendingFor(item.id)!.candidateQuestionIds[0], roundMode: 'NEW_ROUND' })"
                  >新增一轮问答</button>
                </div>
              </template>
            </section>

            <details v-if="item.recognitionRevisions.length || item.state !== 'CONFIRMED'" class="recognition-tools">
              <summary>人工修正{{ item.recognitionRevisions.length ? `（${item.recognitionRevisions.length} 条）` : '' }}</summary>
              <div v-if="item.recognitionRevisions.length" class="revision-history">
                <h4>人工修正历史</h4>
                <div v-for="revision in item.recognitionRevisions" :key="revision.revisionId" class="revision-row">
                  <strong>#{{ revision.revisionNo }}</strong>
                  <span>{{ speakerLabel(revision.beforeSpeaker) }} → {{ speakerLabel(revision.afterSpeaker) }}</span>
                  <span>{{ revision.reason || '未填写原因' }}</span>
                  <span>{{ revision.actorId || '未记录人员' }}</span>
                  <time>{{ formatDate(revision.createdAt) }}</time>
                </div>
              </div>

              <div v-if="item.state !== 'CONFIRMED'" class="recognition-correction">
                <h4>人工修正</h4>
                <p>请确认说话人并填写修正原因。</p>
                <div class="correction-controls">
                  <select
                    :value="correctionRole(item)"
                    @change="correctionSpeaker[item.id] = ($event.target as HTMLSelectElement).value as TemporaryAsrSpeaker"
                  >
                    <option value="SUSPECT">嫌疑人</option>
                    <option value="INTERROGATOR">主审民警</option>
                    <option value="RECORDER">记录民警</option>
                    <option value="UNKNOWN">未知人员</option>
                  </select>
                  <input v-model="correctionReason[item.id]" placeholder="填写人工修正原因（必填）" maxlength="512" />
                  <button class="correction-submit" :disabled="!(correctionReason[item.id] || '').trim()" @click="submitCorrection(item)">保存修正</button>
                </div>
              </div>
            </details>
          </article>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.capture-control .capture-toggle {
  width: 142px;
  min-width: 142px;
}

.dialogue-zones {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px 14px;
  overflow: hidden;
}

.dialogue-upper-zones {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, .7fr) minmax(0, 1.3fr);
  gap: 10px;
}

.dialogue-region {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--line-300);
  border-radius: 10px;
  background: var(--surface);
}

.region-heading {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px 7px;
  color: var(--ink-700);
  font: var(--text-xs)/1.45 system-ui, sans-serif;
}

.region-heading strong {
  color: var(--navy-700);
  font-size: var(--text-sm);
}

.capture-meter-state {
  color: var(--ink-500);
  font-size: var(--text-xs);
  line-height: 1.4;
  white-space: nowrap;
}

.capture-meter-waveform {
  flex: 1 1 auto;
  min-height: 0;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: stretch;
  margin: 0 12px 10px;
}

.waveform-placeholder {
  display: grid;
  place-items: center;
  width: 100%;
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.transcript-heading > div,
.recognition-heading > div {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.transcript-content,
.recognition-list {
  min-height: 0;
  flex: 1 1 auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.transcript-content {
  padding: 0 14px 12px;
  scroll-behavior: smooth;
}

.transcript-paragraph {
  margin: 0;
  color: var(--navy-900);
  font-size: var(--text-sm);
  line-height: 1.75;
  white-space: normal;
  overflow-wrap: anywhere;
}

.transcript-fragment {
  cursor: text;
}

.transcript-fragment.selected {
  background: var(--surface-muted);
}

.transcript-live-partial {
  color: var(--primary-500);
}

.transcript-live-partial.idle {
  color: var(--ink-400);
}

.latest-inline-button {
  flex: 0 0 auto;
  border: 1px solid var(--ink-300);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--primary-700);
  background: var(--surface);
  font-size: var(--text-xs);
  cursor: pointer;
}

.recognition-count {
  flex: 0 0 auto;
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.recognition-list {
  padding: 0 12px 10px;
}

.recognition-entry {
  padding: 5px 0;
  border-top: 1px solid var(--canvas);
}

.recognition-row {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 7px;
  min-height: 30px;
}

.recognition-entry-actions {
  display: flex;
  justify-content: flex-end;
  padding: 0 2px 3px;
}

.recognition-transfer-button {
  border: 1px solid var(--ink-300);
  border-radius: 999px;
  padding: 3px 9px;
  color: var(--primary-600);
  background: var(--surface);
  font-size: var(--text-xs);
  cursor: pointer;
}

.recognition-transfer-button.selected {
  border-color: var(--primary-500);
  color: var(--surface);
  background: var(--primary-500);
}

.recognition-time {
  color: var(--ink-500);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}

.recognition-excerpt {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--ink-700);
  font-size: var(--text-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.speaker-result-chip {
  max-width: 130px;
  overflow: hidden;
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--primary-600);
  background: var(--surface-muted);
  font-size: var(--text-xs);
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.speaker-result-chip.review {
  color: var(--warning-600);
  background: var(--warning-100);
}

.recognition-result-state {
  color: var(--success-700);
  font-size: var(--text-xs);
  white-space: nowrap;
}

.recognition-result-state.review {
  color: var(--warning-600);
}

.recognition-empty {
  margin: 12px 2px;
  color: var(--ink-400);
  font-size: var(--text-xs);
}

@media (max-width: 1100px) {
  .recognition-row {
    grid-template-columns: 54px minmax(0, 1fr) auto;
  }
  .recognition-result-state {
    grid-column: 2 / -1;
    margin-top: -4px;
  }
}

.fragment-lineage {
  margin: 8px 0 0;
  padding: 7px 9px;
  border: 1px solid var(--line-300);
  border-radius: 8px;
  color: var(--ink-500);
  background: var(--surface-sunken);
  font-size: var(--text-xs);
}

.fragment-lineage summary {
  cursor: pointer;
}

.fragment-lineage-row {
  display: flex;
  gap: 8px;
  padding-top: 6px;
}

.speaker-prefix { color: var(--primary-700); }
.evidence-title { font-weight: 700; color: var(--navy-900); }
.evidence-store-badge {
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--success-100);
  color: var(--success-700);
  font-weight: 700;
}
.partial-turn .dialogue-bubble { border-style: solid; }
.partial-turn.idle .dialogue-bubble { opacity: .4; }
.revision-history,
.recognition-correction {
  margin: 0 10px 10px;
  padding-top: 9px;
  border-top: 1px solid rgba(76, 112, 156, .16);
}
.revision-history h4,
.recognition-correction h4 { margin: 0 0 6px; font-size: var(--text-xs); color: var(--navy-900); }
.revision-row {
  display: grid;
  grid-template-columns: auto 1fr 1.4fr 1fr auto;
  gap: 6px;
  padding: 5px 0;
  color: var(--ink-500);
}
.recognition-correction p { margin: 0 0 7px; color: var(--ink-500); }
.correction-controls { display: grid; grid-template-columns: 120px 1fr auto; gap: 6px; }
.correction-controls select,
.correction-controls input {
  min-width: 0;
  border: 1px solid var(--line-300);
  border-radius: 7px;
  padding: 6px 8px;
  background: var(--surface);
}
.correction-submit {
  border: 0;
  border-radius: 7px;
  padding: 6px 10px;
  background: var(--primary-600);
  color: white;
  cursor: pointer;
}
.correction-submit:disabled { opacity: .45; cursor: not-allowed; }
@media (max-width: 900px) {
  .revision-row { grid-template-columns: auto 1fr; }
  .correction-controls { grid-template-columns: 1fr; }
}
.recognition-tools { margin-top: 6px; color: var(--ink-500); font-size: var(--text-xs); }
.recognition-tools summary { cursor: pointer; padding: 4px; }
.qa-review-rail { margin-bottom: 10px; color: var(--ink-500); font-size: var(--text-xs); }
.qa-review-rail summary { cursor: pointer; padding: 4px 2px; }
.qa-review-rail[open] { display: grid; gap: 8px; }
.qa-review-card { border: 1px solid var(--warning-600); background: var(--warning-100); border-radius: 10px; padding: 10px; }
.qa-review-card header { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.qa-review-card p { margin: 6px 0; line-height: 1.45; }
.qa-status-chip { display: inline-flex; padding: 2px 8px; border-radius: 999px; background: var(--warning-600); color: var(--warning-700); font-weight: 800; }
.qa-suggestion { color: var(--ink-500); }
.qa-review-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.qa-review-actions button { cursor: grab; }
.qa-review-actions .qa-ignore { cursor: pointer; }
.qa-routing-status { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border-radius: 8px; background: var(--success-100); color: var(--success-700); font-size: var(--text-xs); }
.qa-routing-status small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qa-rollback { margin-left: auto; border: 1px solid var(--warning-600); border-radius: 6px; padding: 3px 7px; background: var(--surface); color: var(--warning-700); cursor: pointer; }
.qa-status-muted { background: var(--surface-sunken); color: var(--ink-500); opacity: .78; }
.raw-fragment-list { display: grid; gap: 6px; padding: 9px 10px; border-top: 1px solid rgba(76, 112, 156, .16); }
.raw-fragment-list div { display: grid; gap: 2px; }
.raw-fragment-list strong { color: var(--ink-700); }
.raw-fragment-list small { color: var(--ink-500); }
</style>
