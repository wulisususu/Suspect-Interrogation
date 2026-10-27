import { describe, expect, it } from 'vitest'
import { auditActionLabel, normalizeAuditEntry } from './audit'

describe('audit entries', () => {
  it('normalises backend rows and parses ISO timestamps', () => {
    const entry = normalizeAuditEntry({ id: 'a', action: 'CASE_CREATE', targetType: 'CASE', targetId: 'C-1', actorId: '张伟', createdAt: '2026-10-26T18:02:10.752154+00:00' })
    expect(entry).toEqual({ id: 'a', action: 'CASE_CREATE', targetType: 'CASE', targetId: 'C-1', actorId: '张伟', createdAt: Date.parse('2026-10-26T18:02:10.752Z') })
  })

  it('tolerates missing fields', () => {
    expect(normalizeAuditEntry({})).toEqual({ id: '', action: '', targetType: '', targetId: '', actorId: '', createdAt: null })
  })

  it('names known actions and falls back to the raw code', () => {
    expect(auditActionLabel('CASE_CREATE')).toBe('建案')
    expect(auditActionLabel('IDENTITY_CONFIRM')).toBe('身份确认')
    expect(auditActionLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })
})
