import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()
const del = vi.fn()

vi.mock('./http', () => ({ http: { get, post, patch, delete: del } }))

const envelope = (data: unknown) => ({ data: { ok: true, code: 'OK', message: 'OK', data } })

describe('officer auth and signature client', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    patch.mockReset()
    del.mockReset()
  })

  it('posts credentials with the camelCase body the backend expects', async () => {
    post.mockResolvedValue(envelope({ authenticated: true, officer: { badgeNumber: '038291' } }))
    const { loginOfficer } = await import('./officers')
    const session = await loginOfficer('038291', 'secret-password')
    expect(post).toHaveBeenCalledWith('/api/v1/auth/login', { badgeNumber: '038291', password: 'secret-password' })
    expect(session.authenticated).toBe(true)
  })

  it('surfaces the backend message for a rejected login', async () => {
    post.mockResolvedValue({ data: { ok: false, code: 'AUTH_INVALID_CREDENTIALS', message: '警号或密码不正确' } })
    const { loginOfficer } = await import('./officers')
    await expect(loginOfficer('038291', 'wrong')).rejects.toThrow('警号或密码不正确')
  })

  it('encodes badge numbers in signature paths and keeps the alias', async () => {
    get.mockResolvedValue(envelope([]))
    post.mockResolvedValue(envelope({ id: 's1' }))
    const { fetchOfficerSignatures, saveOfficerSignature } = await import('./officers')
    await fetchOfficerSignatures('03 8291')
    expect(get).toHaveBeenCalledWith('/api/v1/officers/03%208291/signatures')
    await saveOfficerSignature('038291', 'data:image/png;base64,AAA')
    expect(post).toHaveBeenCalledWith('/api/v1/officers/038291/signatures', { imageData: 'data:image/png;base64,AAA' })
  })

  it('toggles signature state through the signature id endpoint', async () => {
    patch.mockResolvedValue(envelope({ id: 's1', enabled: false }))
    const { setOfficerSignatureEnabled } = await import('./officers')
    await setOfficerSignatureEnabled('s1', false)
    expect(patch).toHaveBeenCalledWith('/api/v1/officer-signatures/s1', { enabled: false })
  })

  it('reports an unconfigured roster instead of pretending the login failed', async () => {
    get.mockResolvedValue(envelope({ configured: false, authenticated: false, officer: null }))
    const { fetchAuthSession } = await import('./officers')
    const session = await fetchAuthSession()
    expect(session.configured).toBe(false)
    expect(session.officer).toBeNull()
  })
})
