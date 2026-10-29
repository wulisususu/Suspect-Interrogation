import { http } from './http'

export interface Officer {
  badgeNumber: string
  name: string
  unit: string
  enabled: boolean
  isAdmin: boolean
  displayName: string
}

export interface OfficerSignature {
  id: string
  badgeNumber: string
  version: number
  imageData: string
  enabled: boolean
  createdAt: string
}

export interface SignatureUse {
  id: string
  caseId: string
  snapshotId: string | null
  signatureId: string
  badgeNumber: string
  actorId: string | null
  usedAt: string
}

export interface AuthSession {
  configured: boolean
  required: boolean
  authenticated: boolean
  locked: boolean
  officer: Officer | null
  expiresAt?: string
  exemptionUntil?: string
  exemptionRemainingSeconds?: number
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    const envelope = payload as { ok: boolean; data?: T; code?: string; message?: string }
    if (!envelope.ok) throw new Error(envelope.message || envelope.code || '民警接口返回错误')
    return ('data' in envelope ? envelope.data : payload) as T
  }
  return payload as T
}

export async function fetchAuthSession(): Promise<AuthSession> {
  const response = await http.get('/api/v1/auth/session')
  return unwrap<AuthSession>(response.data)
}

export async function loginOfficer(badgeNumber: string, password: string): Promise<AuthSession> {
  const response = await http.post('/api/v1/auth/login', { badgeNumber, password })
  return unwrap<AuthSession>(response.data)
}

export async function lockOfficerPanel(): Promise<AuthSession> {
  const response = await http.post('/api/v1/auth/lock')
  return unwrap<AuthSession>(response.data)
}

export async function unlockOfficerPanel(password?: string): Promise<AuthSession> {
  const response = await http.post('/api/v1/auth/unlock', password ? { password } : {})
  return unwrap<AuthSession>(response.data)
}

export async function logoutOfficer(): Promise<void> {
  await http.post('/api/v1/auth/logout')
}

export async function fetchOfficers(activeOnly = false): Promise<Officer[]> {
  const response = await http.get('/api/v1/officers', { params: { activeOnly } })
  return unwrap<Officer[]>(response.data)
}

export async function fetchOfficerSignatures(badgeNumber: string): Promise<OfficerSignature[]> {
  const response = await http.get(`/api/v1/officers/${encodeURIComponent(badgeNumber)}/signatures`)
  return unwrap<OfficerSignature[]>(response.data)
}

export async function saveOfficerSignature(badgeNumber: string, imageData: string): Promise<OfficerSignature> {
  const response = await http.post(`/api/v1/officers/${encodeURIComponent(badgeNumber)}/signatures`, { imageData })
  return unwrap<OfficerSignature>(response.data)
}

export async function setOfficerSignatureEnabled(signatureId: string, enabled: boolean): Promise<OfficerSignature> {
  const response = await http.patch(`/api/v1/officer-signatures/${encodeURIComponent(signatureId)}`, { enabled })
  return unwrap<OfficerSignature>(response.data)
}

export async function fetchSignatureUses(badgeNumber: string, limit = 50): Promise<SignatureUse[]> {
  const response = await http.get(`/api/v1/officers/${encodeURIComponent(badgeNumber)}/signature-uses`, {
    params: { limit },
  })
  return unwrap<SignatureUse[]>(response.data)
}
