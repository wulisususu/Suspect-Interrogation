import { describe, expect, it } from 'vitest'

import panelSource from './MossTranscriptionPanel.vue?raw'
import workspaceSource from '../views/InterrogationWorkspace.vue?raw'
import apiSource from '../api/mossTranscription.ts?raw'
import utilsSource from '../utils/mossTranscription.ts?raw'

describe('moss transcription panel contract', () => {
  it('is no longer mounted in the interrogation workspace (design top bar has no MOSS tool)', () => {
    expect(workspaceSource).not.toContain('MossTranscriptionPanel')
  })

  it('shows a dedicated MOSS-disabled banner and blocks submission', () => {
    expect(panelSource).toContain('MOSS 未启用')
    expect(panelSource).toContain('moss-disabled-banner')
    expect(panelSource).toContain('isMossDisabledError(error)')
    expect(panelSource).toContain(':disabled="mossDisabled')
  })

  it('maps states through the shared ui constants instead of inline literals', () => {
    expect(panelSource).toContain("from '../utils/mossTranscription'")
    expect(utilsSource).toContain("RECOVERY_REQUIRED: { icon: '⚠️', label: '需恢复', tone: 'recover' }")
    expect(utilsSource).toContain("COMPLETED: { icon: '✅', label: '完成', tone: 'done' }")
    expect(utilsSource).toContain("QUEUED: { icon: '🕒', label: '排队', tone: 'queued' }")
  })

  it('polls active states every 5 seconds and clears the timer on unmount', () => {
    expect(panelSource).toContain('MOSS_POLL_INTERVAL_MS = 5_000')
    expect(panelSource).toContain('window.setInterval')
    expect(panelSource).toContain('window.clearInterval')
    expect(panelSource).toContain('onUnmounted(stopPolling)')
    expect(utilsSource).toContain("'BUILDING_EMBEDS',")
    expect(utilsSource).toContain('export const MOSS_ACTIVE_POLL_STATES')
  })

  it('loads the transcript when completed and refreshes on revisionNo change with a state-driven fallback', () => {
    expect(panelSource).toContain('await syncTranscript(caseId, false)') // 每个轮询周期核对 revisionNo
    expect(panelSource).toContain("if (next.state === 'COMPLETED') await syncTranscript(caseId, false)")
    expect(panelSource).toContain('loadedRevisionNo')
    expect(panelSource).toContain('nextRevision === null') // 字段缺失 → 状态驱动
    expect(panelSource).toContain('刷新转写')
  })

  it('renders the window list with audio-clock ranges, state icon and segment count', () => {
    expect(panelSource).toContain('formatAudioClockMs(windowItem.startMs)')
    expect(panelSource).toContain('mossWindowStateUi(windowItem.state).icon')
    expect(panelSource).toContain('{{ windowItem.segmentCount }} 段')
  })

  it('renders transcript segments as [HH:MM:SS] role (GSxx) with ascending order', () => {
    expect(panelSource).toContain('sortMossSegments')
    expect(panelSource).toContain('mossSegmentHeading(segment)')
    expect(utilsSource).toContain('return [...segments].sort((a, b) => {')
  })

  it('edits and saves the speaker mapping then refreshes the transcript roles', () => {
    expect(panelSource).toContain('putMossSpeakerMapping')
    expect(panelSource).toContain('新增映射')
    expect(panelSource).toContain('保存映射')
    expect(panelSource).toContain('await syncTranscript(caseId, true) // role 展示值来自当前映射，保存后强制刷新')
  })

  it('offers resubmission for failed/cancelled/recovery states using the stored audio path', () => {
    expect(panelSource).toContain('resubmitMossTranscription')
    expect(panelSource).toContain('status.value?.audioPath || audioPathInput.value')
    expect(utilsSource).toContain("MOSS_RESUBMITTABLE_STATES: readonly MossTranscriptionState[] = ['FAILED', 'CANCELLED', 'RECOVERY_REQUIRED']")
  })

  it('keeps the backend route contract verbatim (spec §32.3)', () => {
    expect(apiSource).toContain('/moss-transcription${suffix}')
    expect(apiSource).toContain("'/resubmit'")
    expect(apiSource).toContain('/moss-speaker-mapping')
    expect(apiSource).toContain("MOSS_DISABLED_CODE = 'MOSS_DISABLED'")
  })
})
