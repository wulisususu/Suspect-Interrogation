import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it } from 'vitest'

import LiveDialoguePanel from './LiveDialoguePanel.vue'

async function renderMeter(options: {
  running: boolean
  samples?: Array<{ sampleCount: number; sampleRate: number; rms: number; peak: number }>
  updatedAt?: number | null
}) {
  return renderToString(createSSRApp(LiveDialoguePanel, {
    caseId: 'case-1',
    dialogue: [],
    partialText: '',
    pendingQuestions: [],
    qaUnits: [],
    questions: [],
    suspectName: '张某',
    captureRunning: options.running,
    captureStatus: {
      caseId: 'case-1',
      captureSessionId: 'capture-1',
      running: options.running,
      startedAt: Date.now() - 2000,
      sampleRate: 16000,
      partialText: '',
      fragments: [],
      audioLevels: options.samples ?? [],
      audioLevelUpdatedAt: options.updatedAt ?? null,
    },
    fragmentHistory: () => [],
    captureBusy: false,
    captureAvailable: true,
    captureElapsedMs: 2000,
  }))
}

describe('live dialogue audio meter', () => {
  it('renders the Canvas waveform for live PCM data and keeps the real capture duration', async () => {
    const html = await renderMeter({
      running: true,
      samples: [
        { sampleCount: 160, sampleRate: 16000, rms: 0, peak: 0 },
        { sampleCount: 320, sampleRate: 16000, rms: 8192, peak: 16384 },
      ],
      updatedAt: Date.now(),
    })

    expect(html).toContain('aria-label="实时麦克风输入振幅波形"')
    expect(html.indexOf('waveform-region')).toBeLessThan(html.indexOf('transcript-region'))
    expect(html).toContain('class="recorder-waveform-canvas"')
    expect(html).toContain('实时音频')
    expect(html).toContain('停止录音 00:02')
  })

  it('shows waiting and stale states without creating waveform bars', async () => {
    const waiting = await renderMeter({ running: true })
    expect(waiting).toContain('等待音频输入')
    expect(waiting).not.toContain('<i')
    expect(waiting).not.toContain('class="recorder-waveform-canvas"')

    const stale = await renderMeter({
      running: true,
      samples: [{ sampleCount: 160, sampleRate: 16000, rms: 512, peak: 1024 }],
      updatedAt: Date.now() - 2000,
    })
    expect(stale).toContain('暂无新音频信号')
  })

  it('hides the last waveform after recording stops', async () => {
    const html = await renderMeter({
      running: false,
      samples: [{ sampleCount: 160, sampleRate: 16000, rms: 4096, peak: 8192 }],
      updatedAt: Date.now(),
    })

    expect(html).toContain('录音未进行')
    expect(html).not.toContain('class="recorder-waveform-canvas"')
  })
})
