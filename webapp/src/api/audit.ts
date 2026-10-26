import { getRuntimeAdapter } from '../runtime'

export interface AuditEntry {
  id: string
  action: string
  targetType: string
  targetId: string
  actorId: string
  createdAt: number | null
}

const ACTION_LABELS: Record<string, string> = {
  CASE_CREATE: '建案',
  CASE_UPDATE: '修改案件信息',
  IDENTITY_CONFIRM: '身份确认',
  FACT_UPDATE: '修改要素',
  SESSION_START: '开始审讯',
  SESSION_PAUSE: '暂停审讯',
  SESSION_RESUME: '恢复审讯',
  SESSION_FINISH: '结束审讯',
  DOCUMENT_FREEZE: '定稿冻结',
  DOCUMENT_SIGN: '签名',
  REPORT_GENERATED: '归档',
}

export function auditActionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

export function normalizeAuditEntry(raw: Record<string, unknown>): AuditEntry {
  const text = (value: unknown) => (typeof value === 'string' ? value : '')
  const parsed = typeof raw.createdAt === 'string' ? Date.parse(raw.createdAt) : typeof raw.createdAt === 'number' ? raw.createdAt : Number.NaN
  return {
    id: text(raw.id),
    action: text(raw.action),
    targetType: text(raw.targetType),
    targetId: text(raw.targetId),
    actorId: text(raw.actorId),
    createdAt: Number.isFinite(parsed) ? parsed : null,
  }
}

/** 案件操作日志（后端 audit.list，只读）。 */
export async function fetchCaseAudit(caseId: string): Promise<AuditEntry[]> {
  const rows = await getRuntimeAdapter().invoke<unknown>('audit.list', { caseId })
  return Array.isArray(rows) ? rows.map((row) => normalizeAuditEntry((row ?? {}) as Record<string, unknown>)) : []
}
