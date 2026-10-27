import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// 每个用例都 await import('./interrogation') 装载整张 store 依赖图；全量并行跑时
// 首次装载会超过默认 5s（本机负载敏感，实测 1s~6s 波动），因此放宽超时。
const SUITE_TIMEOUT = { timeout: 20_000 }

describe('interrogation capture event reducer', SUITE_TIMEOUT, () => {
  beforeEach(() => {
    vi.stubGlobal('location', { search: '' })
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps final text visible before speaker resolution and replaces superseded parents once', async () => {
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    const fragment = (id: string, ordinal: number) => ({
      id,
      fragmentId: id,
      caseId: 'case-1',
      captureSessionId: 'capture-1',
      ordinal,
      startedAtMs: ordinal * 1000,
      endedAtMs: (ordinal + 1) * 1000,
      rawText: '问到哪了？',
      editedText: '问到哪了？',
      speaker: 'UNKNOWN',
      speakerSource: 'UNASSIGNED',
      state: 'PENDING',
      createdAt: Date.now(),
      updatedAt: Date.now(),
    })
    const replacement = {
      event: 'ASR_FRAGMENT_REPLACED',
      payload: {
        parentFragmentId: 'f1',
        jobId: 'job-1',
        fragments: [fragment('f2', 1), fragment('f3', 2)],
      },
    }

    store.applyCaptureEvent({ event: 'ASR_FRAGMENT', payload: fragment('f1', 0) })
    expect(store.activeFragments.map((item) => item.id)).toEqual(['f1'])
    expect(store.activeFragments[0].speaker).toBe('UNKNOWN')

    store.applyCaptureEvent(replacement)
    store.applyCaptureEvent(replacement)

    expect(store.activeFragments.map((item) => item.id)).toEqual(['f2', 'f3'])
    expect(store.fragmentHistory('f1').map((item) => item.id)).toEqual(['f1', 'f2', 'f3'])
  })

  it('keeps only real levels for the active capture across status refreshes', async () => {
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    const recordingStatus = {
      caseId: 'case-1',
      captureSessionId: 'capture-1',
      running: true,
      startedAt: Date.now(),
      sampleRate: 16000,
      partialText: '',
      fragments: [],
    }
    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: recordingStatus })
    store.applyCaptureEvent({ event: 'AUDIO_LEVEL', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', sampleCount: 160, sampleRate: 16000, rms: 12, peak: 40,
    } })
    store.applyCaptureEvent({ event: 'AUDIO_LEVEL', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', sampleCount: 320, sampleRate: 16000, rms: 0, peak: 0,
    } })
    store.applyCaptureEvent({ event: 'AUDIO_LEVEL', payload: {
      caseId: 'case-1', captureSessionId: 'capture-old', sampleCount: 480, sampleRate: 16000, rms: 100, peak: 100,
    } })

    expect(store.capture.audioLevels?.map((sample) => sample.peak)).toEqual([40, 0])

    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: recordingStatus })

    expect(store.capture.audioLevels?.map((sample) => sample.peak)).toEqual([40, 0])
    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: { ...recordingStatus, captureSessionId: 'capture-2' } })
    expect(store.capture.audioLevels).toEqual([])
  })

  it('bounds audio meter history to the latest 80 real samples', async () => {
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', running: true,
      startedAt: Date.now(), sampleRate: 16000, partialText: '', fragments: [],
    } })

    for (let index = 0; index < 300; index += 1) {
      store.applyCaptureEvent({ event: 'AUDIO_LEVEL', payload: {
        caseId: 'case-1', captureSessionId: 'capture-1',
        sampleCount: (index + 1) * 160, sampleRate: 16000, rms: index, peak: index,
      } })
    }

    expect(store.capture.audioLevels).toHaveLength(240)
    expect(store.capture.audioLevels?.[0].peak).toBe(60)
    expect(store.capture.audioLevels?.[239].peak).toBe(299)
  })

  it('computes elapsed capture time from the active status start time', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(10_000)
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', running: true,
      startedAt: 8_000, sampleRate: 16000, partialText: '', fragments: [],
    } })

    expect(store.captureElapsedMs).toBe(2_000)
    vi.advanceTimersByTime(1_000)
    expect(store.captureElapsedMs).toBe(3_000)
  })
})

describe('interrogation realtime status events', SUITE_TIMEOUT, () => {
  beforeEach(() => {
    vi.stubGlobal('location', { search: '' })
    setActivePinia(createPinia())
  })

  it('keeps the local fragment list when only a lightweight recording signal arrives', async () => {
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', running: true,
      startedAt: Date.now(), sampleRate: 16000, partialText: '', fragments: [],
    } })
    store.applyCaptureEvent({ event: 'ASR_FRAGMENT', payload: {
      id: 'f1', fragmentId: 'f1', caseId: 'case-1', captureSessionId: 'capture-1',
      ordinal: 0, startedAtMs: 0, endedAtMs: 1000, rawText: '问', editedText: '问',
      speaker: 'SUSPECT', speakerSource: 'MODEL', state: 'PENDING',
      createdAt: Date.now(), updatedAt: Date.now(),
    } })
    expect(store.capture.fragments).toHaveLength(1)

    // 后端推送只带 running（别的终端开/停录音），不能把本机片段清空。
    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', running: true,
    } })
    expect(store.capture.fragments).toHaveLength(1)

    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: {
      caseId: 'case-1', captureSessionId: 'capture-1', running: false, active: false,
    } })
    expect(store.capture.fragments).toHaveLength(1)
  })

  it('applies a pushed session state so another terminal pause shows up locally', async () => {
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    store.session = { ...store.session, id: 'session-1', caseId: 'case-1', status: 'RUNNING' }

    store.applySessionState({
      id: 'session-1', caseId: 'case-1', status: 'PAUSED', stage: 'STATEMENT',
      updatedAt: Date.now(),
    }, { caseId: 'case-1', generation: 0 })

    expect(store.session.status).toBe('PAUSED')
  })
})
