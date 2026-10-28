import { getRuntimeAdapter } from '../runtime'

export interface AuditEntry {
  id: string
  action: string
  targetType: string
  targetId: string
  actorId: string
  createdAt: number | null
}

/** 后端审计动作码 → 业务名称（覆盖 linux/backend/app 中全部 audit 动作）；原始码保留在悬停提示里。 */
const ACTION_LABELS: Record<string, string> = {
  CASE_CREATE: '建案',
  CASE_UPDATE: '修改案件信息',
  IDENTITY_READ: '读取身份证',
  IDENTITY_CONFIRM: '身份确认',
  IDENTITY_BYPASS_LEGACY_COMPAT: '身份确认（旧版兼容）',
  FACT_UPDATE: '修改要素',
  SESSION_START: '开始询问',
  SESSION_PAUSE: '暂停询问',
  SESSION_RESUME: '继续询问',
  SESSION_FINISH: '结束询问',
  SESSION_CHANGE_STAGE: '切换询问阶段',
  ASR_FRAGMENT_CONFIRM: '确认转写片段',
  ASR_FRAGMENT_DISCARD: '丢弃转写片段',
  ASR_FRAGMENT_UPDATE: '人工修正转写',
  ASR_SPEAKER_DECISION: '识别说话人',
  ASR_SPEAKER_LOW_CONFIDENCE: '说话人识别待确认',
  ASR_SPEAKER_FALLBACK: '说话人识别降级',
  QA_CREATE: '新增问答',
  QA_UPDATE: '修改问答',
  QA_MARK: '标记问答',
  QA_ROUTE_AUTO_APPLIED: '问答自动归位',
  QA_ROUTE_MANUAL_APPLIED: '问答人工归位',
  QA_ROUTE_REVIEW_REQUIRED: '问答待人工处置',
  QA_ROUTE_CONFIDENCE_REVIEW_REQUIRED: '问答归位待确认',
  QA_ROUTE_ROLLED_BACK: '撤回问答归位',
  QA_ROUTING_RECOVERY_REQUIRED: '问答整理待恢复',
  DOCUMENT_FREEZE: '定稿冻结',
  SIGNATURE_SAVE: '签名',
  DOCUMENT_SIGN: '签名',
  REPORT_GENERATED: '签署归档',
  CASE_VOICE_ROLE_DRAFT_SAVE: '保存声纹角色草稿',
  SESSION_VOICE_ROLE_BIND: '绑定声纹角色',
  SUSPECT_VOICEPRINT_ENROLL: '登记被询问人声纹',
  SUSPECT_VOICEPRINT_REENROLL: '重新登记被询问人声纹',
  OFFICER_VOICEPRINT_ENROLL: '登记民警声纹',
  OFFICER_VOICEPRINT_UPDATE: '更新民警声纹',
  OFFICER_VOICEPRINT_REVOKE: '停用民警声纹',
  OFFICER_VOICEPRINT_SAMPLE_DISABLE: '停用声纹样本',
  SPEAKER_DEVICE_CALIBRATION_RECOMPUTE: '重新校准说话人识别',
  SPEAKER_REFERENCE_REBUILD: '重建说话人参考',
}

const TARGET_LABELS: Record<string, string> = {
  CASE: '案件',
  PERSON: '被询问人',
  FACT: '要素',
  SESSION: '询问会话',
  ASR_FRAGMENT: '转写片段',
  QA: '问答',
  QA_UNIT: '问答组',
  DOCUMENT: '笔录文书',
  SIGNATURE: '签名',
  CASE_VOICE_ROLE_DRAFT: '声纹角色草稿',
  SESSION_VOICE_ASSIGNMENT: '声纹角色绑定',
  SUSPECT_VOICEPRINT: '被询问人声纹',
  OFFICER_VOICEPRINT: '民警声纹',
  OFFICER_VOICE_PROFILE: '民警声纹档案',
  OFFICER_VOICE_SAMPLE: '民警声纹样本',
  SPEAKER_DEVICE_CALIBRATION: '说话人识别校准',
}

export function auditActionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

/** 对象摘要：业务名称 + 编号尾号；案件直接显示案号。 */
export function auditTargetLabel(entry: Pick<AuditEntry, 'targetType' | 'targetId'>): string {
  const label = TARGET_LABELS[entry.targetType] ?? entry.targetType
  if (!entry.targetId) return label
  if (entry.targetType === 'CASE') return `案 ${entry.targetId}`
  return `${label} · …${entry.targetId.slice(-6)}`
}

/** 操作人：后端自动流程不带操作人，显示为「系统自动」。 */
export function auditActorLabel(actorId: string): string {
  return actorId.trim() || '系统自动'
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
