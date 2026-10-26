<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AsrCaptureStatus } from '../types/interrogation'
import { listRecoverableBrowserFormalCaptures, recoverBrowserFormalCapture } from '../audio/browserAsrCapture'

const props = defineProps<{
  capture: AsrCaptureStatus
  stage?: 'all' | 'transcription' | 'speaker'
}>()
const stage = computed(() => props.stage ?? 'all')
const pendingLocalFrames = ref(0)
const recoveryBusy = ref(false)
const recoveryMessage = ref('')

const visible = computed(() => Boolean(
  props.capture.recordingStatus || props.capture.asrStatus || props.capture.speakerStatus || props.capture.error,
))
const incomplete = computed(() => props.capture.recordingStatus === 'INCOMPLETE')
const activeFragments = computed(() => props.capture.fragments.filter((fragment) => fragment.state !== 'SUPERSEDED'))
const unresolvedSpeakerCount = computed(() => activeFragments.value.filter((fragment) =>
  fragment.speaker === 'UNKNOWN' || fragment.speakerSource === 'PENDING_ANALYSIS',
).length)
const assignedSpeakerCount = computed(() => activeFragments.value.filter((fragment) =>
  fragment.speaker !== 'UNKNOWN' && fragment.speakerSource !== 'PENDING_ANALYSIS',
).length)
const transcriptLabel = computed(() => {
  const labels: string[] = []
  switch (props.capture.recordingStatus) {
    case 'CAPTURING': labels.push('原始录音正在归档'); break
    case 'COMPLETE': labels.push('原始录音已保存'); break
    case 'INCOMPLETE': labels.push('录音不完整，存在音频缺口'); break
    case 'PENDING': labels.push('录音等待启动'); break
  }
  const status = props.capture.asrStatus
  if (!status) return labels.join(' · ')
  const backlog = Math.max(0, (props.capture.audioSampleCount ?? 0) - (props.capture.asrCursorSample ?? 0))
  const backlogSeconds = Math.ceil(backlog / Math.max(1, props.capture.sampleRate))
  const state = status === 'FINALIZING' || status === 'PENDING'
    ? '文字转写处理中'
    : status === 'COMPLETE'
      ? `文字转写完成（${activeFragments.value.length} 段）`
      : status === 'ERROR'
        ? '文字转写异常'
        : `文字转写：${status}`
  labels.push(backlogSeconds > 0 ? `${state}，约有 ${backlogSeconds} 秒音频待处理` : state)
  return labels.join(' · ')
})
const speakerLabel = computed(() => {
  const status = props.capture.speakerStatus
  if (!status) return ''
  if (status === 'COMPLETE') return `分析已完成 · 已归属 ${assignedSpeakerCount.value} 段${unresolvedSpeakerCount.value ? `，${unresolvedSpeakerCount.value} 段身份待确认` : ''}`
  if (status === 'NEEDS_REVIEW') return `分析完成 · 已归属 ${assignedSpeakerCount.value} 段，${unresolvedSpeakerCount.value} 段待人工复核`
  if (status === 'ERROR') return `声纹分析异常 · ${unresolvedSpeakerCount.value} 段身份待确认`
  if (status === 'QUEUED') return `声纹分析已排队 · ${unresolvedSpeakerCount.value} 段待分析`
  if (status === 'RUNNING') return `声纹分析进行中 · ${unresolvedSpeakerCount.value} 段待确认`
  if (status === 'PENDING') {
    const seconds = Math.floor((props.capture.voicedMs ?? 0) / 1000)
    const fragments = activeFragments.value.length
    if (props.capture.running && (seconds < 10 || fragments < 3)) {
      return `等待素材 · 有效语音 ${seconds}/10 秒、文字片段 ${fragments}/3 段`
    }
    if (props.capture.asrStatus !== 'COMPLETE') return `等待第 1 步转写完成 · ${unresolvedSpeakerCount.value} 段待分析`
    if (!unresolvedSpeakerCount.value) return '没有待分析的文字片段'
    return `等待第 2 步开始 · ${unresolvedSpeakerCount.value} 段待分析`
  }
  return `声纹分析：${status}`
})
const liveTranscriptLabel = computed(() => {
  if (props.capture.liveTranscriptStatus === 'MODEL_NOT_INSTALLED') {
    return '实时转写模型未安装，最终文字仍会保存'
  }
  if (props.capture.liveTranscriptStatus === 'ERROR') {
    return '实时转写暂不可用，最终文字仍会保存'
  }
  return ''
})

watch(
  () => [props.capture.caseId, props.capture.captureSessionId, props.capture.recordingStatus] as const,
  async ([caseId, captureId, recordingStatus]) => {
    pendingLocalFrames.value = 0
    recoveryMessage.value = ''
    if (stage.value === 'speaker' || !caseId || !captureId || recordingStatus !== 'INCOMPLETE') return
    try {
      const captures = await listRecoverableBrowserFormalCaptures(caseId)
      pendingLocalFrames.value = captures.find((capture) => capture.captureId === captureId)?.pendingFrameCount ?? 0
    } catch {
      pendingLocalFrames.value = 0
    }
  },
  { immediate: true },
)

async function recoverLocalAudio() {
  const caseId = props.capture.caseId
  const captureId = props.capture.captureSessionId
  if (!caseId || !captureId || recoveryBusy.value) return
  recoveryBusy.value = true
  recoveryMessage.value = ''
  try {
    await recoverBrowserFormalCapture(caseId, captureId)
    pendingLocalFrames.value = 0
    recoveryMessage.value = '本机音频已补录并进入文字识别'
  } catch (error) {
    try {
      const captures = await listRecoverableBrowserFormalCaptures(caseId)
      pendingLocalFrames.value = captures.find((capture) => capture.captureId === captureId)?.pendingFrameCount ?? 0
    } catch {
      pendingLocalFrames.value = 0
    }
    recoveryMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    recoveryBusy.value = false
  }
}
</script>

<template>
  <div v-if="visible" class="asr-workflow-status" :class="{ incomplete, compact: stage !== 'all' }" role="status" aria-live="polite">
    <template v-if="stage === 'all'">
      <div class="workflow-stage">
        <span class="workflow-stage-number">第 1 步</span>
        <div class="workflow-stage-copy">
          <strong>原始录音与文字转写</strong>
          <span>{{ transcriptLabel || '等待录音' }}</span>
          <span v-if="liveTranscriptLabel" class="live-transcript-warning">{{ liveTranscriptLabel }}</span>
        </div>
      </div>
      <div class="workflow-stage speaker-stage">
        <span class="workflow-stage-number">第 2 步</span>
        <div class="workflow-stage-copy">
          <strong>声纹分析与说话人归属</strong>
          <span>{{ speakerLabel || '等待第 1 步产生文字片段' }}</span>
        </div>
      </div>
    </template>
    <span v-else class="workflow-compact-copy">
      {{ stage === 'transcription' ? transcriptLabel || '等待录音' : speakerLabel || '等待第 1 步产生文字片段' }}
      <span v-if="stage === 'transcription' && liveTranscriptLabel" class="live-transcript-warning">{{ liveTranscriptLabel }}</span>
    </span>
    <span v-if="capture.error" class="workflow-error">{{ capture.error }}</span>
    <div v-if="incomplete && stage !== 'speaker' && pendingLocalFrames" class="local-recovery">
      <span>本机保留了 {{ pendingLocalFrames }} 个尚未归档的音频分片。</span>
      <button type="button" :disabled="recoveryBusy" @click="recoverLocalAudio">
        {{ recoveryBusy ? '正在补录…' : '补录本机音频' }}
      </button>
    </div>
    <span v-if="recoveryMessage" class="workflow-error">{{ recoveryMessage }}</span>
  </div>
</template>

<style scoped>
.asr-workflow-status {
  display: grid;
  gap: 8px;
  padding: 8px 12px;
  color: var(--primary-700);
  background: var(--surface-sunken);
  border-bottom: 1px solid var(--line-300);
  font: 12px/1.45 system-ui, sans-serif;
}

.asr-workflow-status.compact {
  display: block;
  padding: 0;
  border: 0;
  background: transparent;
  font-size: 11px;
}

.workflow-compact-copy {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.workflow-stage {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid var(--line-300);
  border-radius: 7px;
  background: var(--surface);
}

.workflow-stage-number {
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--surface);
  background: var(--primary-600);
  font-size: 11px;
  white-space: nowrap;
}

.workflow-stage-copy {
  display: grid;
  gap: 2px;
}

.workflow-stage-copy strong {
  color: var(--ink-700);
}

.live-transcript-warning {
  color: var(--warning-600);
}

.speaker-stage {
  border-color: var(--line-300);
}

.speaker-stage .workflow-stage-number {
  background: var(--primary-600);
}

.asr-workflow-status.incomplete {
  color: var(--warning-600);
  background: var(--warning-100);
  border-bottom-color: var(--warning-100);
}

.asr-workflow-status.incomplete .workflow-stage {
  border-color: var(--warning-100);
}

.workflow-error {
  flex-basis: 100%;
}

.local-recovery {
  display: flex;
  flex-basis: 100%;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.local-recovery button {
  border: 1px solid var(--warning-600);
  border-radius: 5px;
  padding: 4px 9px;
  color: var(--warning-700);
  background: var(--surface);
  cursor: pointer;
}

.local-recovery button:disabled {
  cursor: wait;
  opacity: 0.65;
}
</style>
