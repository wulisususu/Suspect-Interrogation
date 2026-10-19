import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('interrogation capture event reducer', () => {
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
