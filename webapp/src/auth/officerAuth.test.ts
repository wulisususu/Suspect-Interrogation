import { afterEach, describe, expect, it } from 'vitest'
import { authPrompt, authReasonForError, authReasonForSession, requestOfficerAuth, settleOfficerAuth } from './officerAuth'

afterEach(() => settleOfficerAuth(false))

describe('officer auth prompt', () => {
  it('maps only session failures to a re-verification prompt', () => {
    expect(authReasonForError(401, 'AUTH_SESSION_REQUIRED')).toBe('required')
    expect(authReasonForError(423, 'AUTH_SESSION_LOCKED')).toBe('locked')
    expect(authReasonForError(401, 'AUTH_INVALID_CREDENTIALS')).toBeNull()
    expect(authReasonForError(403, 'AUTH_ADMIN_REQUIRED')).toBeNull()
    expect(authReasonForError(409, 'FORMAL_RECORD_FROZEN')).toBeNull()
  })

  it('derives the needed verification from a session probe and ignores unconfigured rosters', () => {
    expect(authReasonForSession({ configured: false, authenticated: false, locked: false })).toBeNull()
    expect(authReasonForSession({ configured: true, authenticated: false, locked: false })).toBe('required')
    expect(authReasonForSession({ configured: true, authenticated: true, locked: true })).toBe('locked')
    expect(authReasonForSession({ configured: true, authenticated: true, locked: false })).toBeNull()
  })

  it('shares one dialog between concurrent requests and resolves every waiter', async () => {
    const first = requestOfficerAuth('locked')
    const second = requestOfficerAuth('required')
    // A login need supersedes an unlock need; the dialog is not duplicated.
    expect(authPrompt.value).toEqual({ reason: 'required' })
    settleOfficerAuth(true)
    await expect(first).resolves.toBe(true)
    await expect(second).resolves.toBe(true)
    expect(authPrompt.value).toBeNull()
  })
})
