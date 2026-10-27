import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const stopAsrCapture = vi.fn()
const pauseSessionApi = vi.fn()
const finishSessionApi = vi.fn()

vi.mock('../api/interrogation', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/interrogation')>()
  return {
    ...actual,
    stopAsrCapture: (...args: unknown[]) => stopAsrCapture(...args),
    pauseSession: (...args: unknown[]) => pauseSessionApi(...args),
    finishSession: (...args: unknown[]) => finishSessionApi(...args),
  }
})

const runningStatus = {
  caseId: 'case-1',
  captureSessionId: 'capture-1',
  running: true,
  startedAt: Date.now(),
  sampleRate: 16000,
  partialText: '',
  fragments: [],
}

async function runningStore() {
  const { useInterrogationStore } = await import('./interrogation')
  const store = useInterrogationStore()
  store.resetCaseContext('case-1')
  store.nativeCaptureAvailable = true
  store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: runningStatus })
  store.session = { ...store.session, id: 'session-1', caseId: 'case-1', status: 'RUNNING' }
  return store
}

describe('stopping capture before pausing or finishing', () => {
  beforeEach(() => {
    vi.stubGlobal('location', { search: '' })
    setActivePinia(createPinia())
    stopAsrCapture.mockReset()
    pauseSessionApi.mockReset()
    finishSessionApi.mockReset()
  })

  it('cancels the pause when the recording could not be stopped', async () => {
    const store = await runningStore()
    stopAsrCapture.mockRejectedValue(new Error('stop timeout'))

    await store.togglePause()

    expect(pauseSessionApi).not.toHaveBeenCalled()
    expect(store.session.status).toBe('RUNNING')
    expect(store.actionError || store.actionMessage).toContain('取消暂停')
  })

  it('cancels finishing the session when the recording could not be stopped', async () => {
    const store = await runningStore()
    stopAsrCapture.mockRejectedValue(new Error('stop timeout'))

    await store.finishSession()

    expect(finishSessionApi).not.toHaveBeenCalled()
    expect(store.session.status).toBe('RUNNING')
    expect(store.actionError || store.actionMessage).toContain('取消结束')
  })

  it('pauses once the recording is confirmed stopped', async () => {
    const store = await runningStore()
    stopAsrCapture.mockResolvedValue({ ...runningStatus, running: false })
    pauseSessionApi.mockResolvedValue({ ...store.session, status: 'PAUSED' })

    await store.togglePause()

    expect(stopAsrCapture).toHaveBeenCalledTimes(1)
    expect(pauseSessionApi).toHaveBeenCalledWith('case-1')
    expect(store.session.status).toBe('PAUSED')
  })
})
