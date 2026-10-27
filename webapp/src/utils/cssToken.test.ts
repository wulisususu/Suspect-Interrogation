import { describe, expect, it, vi } from 'vitest'
import { cssToken } from './cssToken'

describe('cssToken', () => {
  it('reads the token value from the document root', () => {
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: (name: string) => (name === '--ink-500' ? ' #5b6b83 ' : '') }))
    expect(cssToken('--ink-500', '#000')).toBe('#5b6b83')
    vi.unstubAllGlobals()
  })

  it('falls back when the token is missing or there is no DOM', () => {
    expect(cssToken('--ink-500', '#123456')).toBe('#123456')
  })
})
