import { describe, expect, it } from 'vitest'

describe('superseded audio socket', () => {
  it('only reports the conflict and never stops or restarts the capture owned elsewhere', async () => {
    const source = (await import('./interrogation.ts?raw')).default
    const start = source.indexOf('setBrowserAsrSupersededListener(')
    expect(start).toBeGreaterThan(-1)
    const block = source.slice(start, source.indexOf('\n  })', start))

    expect(block).toContain('capture.value.error')
    // 停止采集会把另一个窗口正在录的那一路停掉，重启则两页互抢同一个采集。
    expect(block).not.toContain('stopCapture')
    expect(block).not.toContain('startCapture')
  })
})
