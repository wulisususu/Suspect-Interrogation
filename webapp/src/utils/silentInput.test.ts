import { describe, expect, it } from 'vitest'
import {
  initialSilentInputState,
  nextSilentInputState,
  SILENT_INPUT_RMS,
  SILENT_INPUT_WINDOW_MS,
  silentInputMessage,
} from './silentInput'

describe('silent microphone detection', () => {
  it('warns once when only noise arrives for the whole window', () => {
    let state = initialSilentInputState()
    const start = 1_000
    // 底噪：峰值约 300
    let step = nextSilentInputState(state, 300, start)
    expect(step.warn).toBe(false)
    state = step
    step = nextSilentInputState(state, 320, start + SILENT_INPUT_WINDOW_MS - 1)
    expect(step.warn).toBe(false)
    state = step
    step = nextSilentInputState(state, 310, start + SILENT_INPUT_WINDOW_MS)
    expect(step.warn).toBe(true)
    // 告警后不再重复打扰
    state = step
    expect(nextSilentInputState(state, 310, start + 60_000).warn).toBe(false)
  })

  it('never warns once real speech has been heard', () => {
    let state = nextSilentInputState(initialSilentInputState(), { rms: SILENT_INPUT_RMS, peak: 0 }, 1_000)
    expect(state.warn).toBe(false)
    expect(state.settled).toBe(true)
    // 之后即使安静下来也不再告警
    expect(nextSilentInputState(state, { rms: 80, peak: 4_000 }, 99_000).warn).toBe(false)
  })

  it('accepts a quieter-but-real voice as sound', () => {
    const state = nextSilentInputState(initialSilentInputState(), { rms: 1_200, peak: 0 }, 1_000)
    expect(state.settled).toBe(true)
    expect(nextSilentInputState(state, { rms: 100, peak: 0 }, 9_000).warn).toBe(false)
  })

  it('names the device so the fault points at something concrete', () => {
    expect(silentInputMessage('AirPods Pro')).toContain('AirPods Pro')
    expect(silentInputMessage()).not.toContain('当前输入')
    expect(silentInputMessage('MacBook 麦克风')).toContain('麦克风没有收到声音')
  })
})
