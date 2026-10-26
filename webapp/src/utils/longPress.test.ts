import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createLongPress } from './longPress'

describe('createLongPress', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('confirms only after the full hold duration', () => {
    const onConfirm = vi.fn()
    const press = createLongPress(800, onConfirm)
    press.start()
    vi.advanceTimersByTime(799)
    expect(onConfirm).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('does nothing when released early', () => {
    const onConfirm = vi.fn()
    const press = createLongPress(800, onConfirm)
    press.start()
    vi.advanceTimersByTime(500)
    expect(press.progress()).toBeCloseTo(500 / 800, 1)
    press.cancel()
    vi.advanceTimersByTime(1000)
    expect(onConfirm).not.toHaveBeenCalled()
    expect(press.progress()).toBe(0)
  })
})
