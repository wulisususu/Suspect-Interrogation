import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const runtimeCaps = vi.fn()

vi.mock('../api/interrogation', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/interrogation')>()
  return {
    ...actual,
    fetchRuntimeCapabilities: (...args: unknown[]) => runtimeCaps(...args),
  }
})

describe('refreshCapabilities self-heal (录音按钮灰死自愈)', () => {
  beforeEach(() => {
    vi.stubGlobal('location', { search: '' })
    setActivePinia(createPinia())
    runtimeCaps.mockReset()
  })

  it('re-checks with force and recovers captureAvailable after a transient failure', async () => {
    // 首查失败已由 store.captureAvailable=false 模拟；这次强制重查直接命中恢复后的能力。
    runtimeCaps.mockResolvedValueOnce({ recording: { state: 'AVAILABLE' }, asr: { state: 'AVAILABLE' } })

    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    store.captureAvailable = false

    const result = await store.refreshCapabilities()

    expect(result).toBe(true)
    expect(store.captureAvailable).toBe(true)
    expect(runtimeCaps).toHaveBeenLastCalledWith(true)
  })

  it('keeps captureAvailable false when the backend still reports unavailable', async () => {
    runtimeCaps.mockResolvedValue({ recording: { state: 'NOT_CONNECTED' }, asr: { state: 'NOT_CONNECTED' } })
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')
    store.captureAvailable = false

    const result = await store.refreshCapabilities()

    expect(result).toBe(false)
    expect(store.captureAvailable).toBe(false)
  })
})
