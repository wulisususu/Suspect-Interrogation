import { describe, expect, it } from 'vitest'
import type { AuthSession } from '../api/officers'
import { sessionAllowsEntry } from './officerAuth'

const base: AuthSession = { configured: true, required: true, authenticated: false, locked: false, officer: null }

describe('sessionAllowsEntry', () => {
  it('lets a logged-in, unlocked officer straight in', () => {
    expect(sessionAllowsEntry({ ...base, authenticated: true })).toBe(true)
    expect(sessionAllowsEntry({ ...base, authenticated: true, locked: true })).toBe(false)
  })

  it('asks for a login whenever the roster is configured or auth is enforced', () => {
    expect(sessionAllowsEntry(base)).toBe(false)
    expect(sessionAllowsEntry({ ...base, configured: false })).toBe(false)
    expect(sessionAllowsEntry({ ...base, configured: false, required: false })).toBe(true)
  })
})
