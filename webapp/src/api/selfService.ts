import { http } from './http'

/** 自助模式中当事人本人的确认动作；后端只写审计留痕，不改正本。 */
export type SelfServiceEventKind = 'IDENTITY_CONFIRM' | 'ANSWER_CONFIRM' | 'ANSWER_UNCONFIRM' | 'HANDOVER'

export interface SelfServiceState {
  caseId: string
  identityConfirmedAt: string | null
  handedOverAt: string | null
  /** 本人已确认、且确认后回答未被改动的题目 */
  confirmedAnswers: { questionId: string; confirmedAt: string }[]
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    const envelope = payload as { ok: boolean; data?: T; message?: string; code?: string }
    if (!envelope.ok) throw new Error(envelope.message || envelope.code || '自助确认接口返回错误')
    return envelope.data as T
  }
  return payload as T
}

export async function fetchSelfServiceState(caseId: string): Promise<SelfServiceState> {
  const response = await http.get(`/api/v1/cases/${encodeURIComponent(caseId)}/self-service`)
  return unwrap<SelfServiceState>(response.data)
}

export async function recordSelfServiceEvent(caseId: string, kind: SelfServiceEventKind, questionId?: string): Promise<SelfServiceState> {
  const response = await http.post(`/api/v1/cases/${encodeURIComponent(caseId)}/self-service/events`, { kind, ...(questionId ? { questionId } : {}) })
  return unwrap<SelfServiceState>(response.data)
}
