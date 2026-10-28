import { describe, expect, it } from 'vitest'
import { auditActionLabel, auditActorLabel, auditTargetLabel, normalizeAuditEntry } from './audit'

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

  it('names the speech-pipeline events that dominate production logs (audit D13)', () => {
    for (const code of ['ASR_SPEAKER_DECISION', 'ASR_SPEAKER_LOW_CONFIDENCE', 'QA_ROUTE_REVIEW_REQUIRED', 'SESSION_CHANGE_STAGE', 'QA_ROUTE_AUTO_APPLIED', 'REPORT_GENERATED']) {
      expect(auditActionLabel(code)).not.toBe(code)
    }
    expect(auditActionLabel('REPORT_GENERATED')).toBe('签署归档')
  })

  it('summarises targets and labels system actions instead of showing raw UUIDs', () => {
    expect(auditTargetLabel({ targetType: 'ASR_FRAGMENT', targetId: 'f3b1c2d4-0000-4000-8000-1234567890ab' })).toBe('转写片段 · …7890ab')
    expect(auditTargetLabel({ targetType: 'CASE', targetId: 'CASE-1' })).toBe('案 CASE-1')
    expect(auditActorLabel('')).toBe('系统自动')
    expect(auditActorLabel('张伟')).toBe('张伟')
  })
})
