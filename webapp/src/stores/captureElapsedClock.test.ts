import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// 实测故障（AAC708）：板钟比局域网浏览器钟快约 9 秒，elapsed = 浏览器 Date.now()
// − 板端 startedAt 在录音开始时是负数，被 Math.max(0,…) 钳成 0——民警按住说话
// 的几秒里计时器一直是 00:00。录音本身没丢（样木、转写都全），纯显示事故。
// 修复：running 上升沿在本机锚定计时起点，不再跨机器比钟。

const runningStatus = (startedAt: number, running = true) => ({
  caseId: 'case-1',
  captureSessionId: 'capture-1',
  running,
  startedAt,
  sampleRate: 16000,
  partialText: '',
  fragments: [],
})

describe('capture elapsed timer is immune to cross-device clock skew', () => {
  beforeEach(() => {
    vi.stubGlobal('location', { search: '' })
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('anchors on the browser clock when the backend clock is ahead', async () => {
    vi.useFakeTimers()
    const browserStart = Date.parse('2026-11-02T06:14:48.000Z')
    const boardAhead = browserStart + 9000 // 板钟快 9 秒
    vi.setSystemTime(browserStart)
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')

    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: runningStatus(boardAhead) })
    expect(store.capture.running).toBe(true)
    expect(store.captureElapsedMs).toBeLessThan(250)

    vi.advanceTimersByTime(6000)
    expect(store.captureElapsedMs).toBeGreaterThanOrEqual(5800)
    expect(store.captureElapsedMs).toBeLessThan(6500)

    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: runningStatus(boardAhead, false) })
    expect(store.captureElapsedMs).toBe(0)
  })

  it('keeps the true backend start time when the clocks agree', async () => {
    vi.useFakeTimers()
    const startedAt = Date.parse('2026-11-02T06:14:48.000Z')
    vi.setSystemTime(startedAt + 1000) // 浏览器晚 1 秒才看到 running 状态
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')

    store.applyCaptureEvent({ event: 'RECORDING_STATE', payload: runningStatus(startedAt) })
    // 后端 startedAt 更早（钟差正常），沿用真实起点而不是当前时刻。
    expect(store.captureElapsedMs).toBeGreaterThanOrEqual(900)

    vi.advanceTimersByTime(2000)
    expect(store.captureElapsedMs).toBeGreaterThanOrEqual(2800)
  })
})
