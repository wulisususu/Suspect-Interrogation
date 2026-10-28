import { describe, expect, it } from 'vitest'
import { officerDisplayName } from './officer'

describe('officerDisplayName', () => {
  it('treats the backend placeholder and blanks as unassigned', () => {
    expect(officerDisplayName('当前警官')).toBe('')
    expect(officerDisplayName('  ')).toBe('')
    expect(officerDisplayName(undefined)).toBe('')
    expect(officerDisplayName('张伟')).toBe('张伟')
  })
})
