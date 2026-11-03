import { http } from './http'

export interface KnowledgeCategory {
  id: string
  name: string
  active: boolean
}

export type KnowledgeStatus = 'verified' | 'pending'
export type KnowledgeKind = 'faq' | 'wiki'
/** 条目效力：失效日期当日起失效；过期 / 未生效 / 被取代的条目不进办案提示。 */
export type KnowledgeValidity = 'current' | 'expired' | 'not_yet_effective' | 'superseded'

/** 引用链：原件路径（sourceRef）+ 依据文件 + 条款/页码 + 文件版本 + 效力区间 + 取代关系。 */
export interface KnowledgeCitation {
  sourceRef?: string | null
  sourceDocument?: string | null
  sourceLocator?: string | null
  sourceVersion?: string | null
  effectiveFrom?: string | null
  effectiveUntil?: string | null
  superseded?: boolean
  supersededById?: string | null
}

export interface KnowledgeEntry extends KnowledgeCitation {
  id: string
  title: string
  categoryId: string
  categoryName: string
  content: string
  keywords: string[]
  active: boolean
  deleted: boolean
  version: number
  kind: KnowledgeKind
  status: KnowledgeStatus
  origin: 'manual' | 'vault'
  vaultUid?: string | null
  sourcePath?: string | null
  sourceSha256?: string | null
  supersededByTitle?: string | null
  validity?: KnowledgeValidity
  /** 作为定稿校验规则适用的模板 backendKey（大写）或案由分类（小写） */
  checkTemplates?: string[]
  createdAt?: string | null
  updatedAt?: string | null
}

export interface GuidanceItem extends KnowledgeEntry {
  score: number
  matchReasons: string[]
  snippet: string
}

export interface DraftQuestion {
  text: string
  entryId: string | null
  entryTitle: string
  entryVersion: number | null
  sourceRef: string | null
  sourceDocument?: string | null
  sourceLocator?: string | null
  sourceVersion?: string | null
  status: KnowledgeStatus
  categoryName: string
}

export interface KnowledgeLink {
  targetTitle?: string
  entryId: string | null
  relation?: string
  resolved?: boolean
  title?: string
}

export interface KnowledgeLinks {
  outgoing: KnowledgeLink[]
  incoming: KnowledgeLink[]
}

export interface KnowledgeVersion {
  id: string
  version: number
  action: string
  data: KnowledgeEntry
  createdAt: string | null
}

export interface ImportReport {
  root: string
  dryRun: boolean
  scanned: number
  added: Array<{ path: string; uid: string; title: string }>
  updated: Array<{ path: string; uid: string; title: string }>
  unchanged: Array<{ path: string; uid?: string }>
  disabled: Array<{ path: string; uid?: string; title?: string }>
  conflicts: Array<{ path: string; uid?: string; reason: string }>
  rejected: Array<{ path: string; reason: string }>
  correctionConflicts: Array<{ wrong: string; kept: string; ignored: string }>
  correctionsAdded: Array<{ wrong: string; right: string }>
  correctionsUpdated: Array<Record<string, unknown>>
  categoriesCreated: string[]
  warnings: string[]
  runId: string | null
}

export interface CheckRuleItem {
  key: string
  label: string
  /** 正本里应能找到的说法，任一出现即视为已记录 */
  terms: string[]
  /** 关联的模板要素；该要素已确认也视为通过 */
  elementKey: string | null
}

export interface CheckRule {
  entryId: string
  title: string
  version: number
  status: KnowledgeStatus
  origin: 'manual' | 'vault'
  categoryName: string
  sourceRef: string | null
  sourcePath: string | null
  vaultUid: string | null
  matchedBy: { scope: 'TEMPLATE' | 'CASE_TYPE'; value: string }
  items: CheckRuleItem[]
}

export interface CaseCheckRules {
  caseId: string | null
  templateKey: string | null
  caseType: string | null
  rules: CheckRule[]
}

export interface TermCorrection {
  id: string
  wrong: string
  right: string
  category: string
  active: boolean
  entryId?: string | null
}

export const VALIDITY_LABELS: Record<KnowledgeValidity, string> = {
  current: '现行有效',
  expired: '已失效',
  not_yet_effective: '尚未生效',
  superseded: '已被取代',
}

/**
 * 一行可核对的出处：《文件》条款（版本）；没有结构化出处时退回原件路径。
 * 例：「《治安管理处罚法》第四十九条（2012 修正）」。
 */
export function formatCitation(citation: KnowledgeCitation): string {
  const document = citation.sourceDocument?.trim()
  const locator = citation.sourceLocator?.trim()
  const version = citation.sourceVersion?.trim()
  if (!document && !locator) return citation.sourceRef?.trim() || ''
  const title = document ? (/^[《〈]/.test(document) ? document : `《${document}》`) : ''
  return `${title}${locator ?? ''}${version ? `（${version}）` : ''}`
}

/** 效力区间文字，如「2013-01-01 起施行 · 2026-01-01 起失效」；都没填时为空。 */
export function formatEffectivePeriod(citation: KnowledgeCitation): string {
  const parts = [
    citation.effectiveFrom ? `${citation.effectiveFrom} 起施行` : '',
    citation.effectiveUntil ? `${citation.effectiveUntil} 起失效` : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    const envelope = payload as { ok: boolean; data?: T; code?: string; message?: string }
    if (!envelope.ok) throw new Error(envelope.message || envelope.code || '知识库接口返回错误')
    return ('data' in envelope ? envelope.data : payload) as T
  }
  return payload as T
}

export async function fetchKnowledgeCategories(): Promise<KnowledgeCategory[]> {
  const response = await http.get('/api/v1/knowledge/categories')
  return unwrap<KnowledgeCategory[]>(response.data)
}

export async function createKnowledgeCategory(name: string): Promise<KnowledgeCategory> {
  const response = await http.post('/api/v1/knowledge/categories', { name })
  return unwrap<KnowledgeCategory>(response.data)
}

export async function fetchKnowledgeEntries(params: {
  categoryId?: string
  q?: string
  status?: KnowledgeStatus
  active?: boolean
} = {}): Promise<KnowledgeEntry[]> {
  const response = await http.get('/api/v1/knowledge/entries', { params })
  return unwrap<KnowledgeEntry[]>(response.data)
}

export async function fetchKnowledgeEntry(entryId: string): Promise<KnowledgeEntry> {
  const response = await http.get(`/api/v1/knowledge/entries/${encodeURIComponent(entryId)}`)
  return unwrap<KnowledgeEntry>(response.data)
}

export async function createKnowledgeEntry(input: {
  title: string
  categoryId: string
  content: string
  keywords?: string[]
  kind?: KnowledgeKind
  status?: KnowledgeStatus
} & KnowledgeCitation): Promise<KnowledgeEntry> {
  const response = await http.post('/api/v1/knowledge/entries', input)
  return unwrap<KnowledgeEntry>(response.data)
}

export async function updateKnowledgeEntry(
  entryId: string,
  patch: Partial<{
    title: string
    categoryId: string
    content: string
    keywords: string[]
    active: boolean
    kind: KnowledgeKind
    status: KnowledgeStatus
  } & KnowledgeCitation>,
): Promise<KnowledgeEntry> {
  const response = await http.patch(`/api/v1/knowledge/entries/${encodeURIComponent(entryId)}`, patch)
  return unwrap<KnowledgeEntry>(response.data)
}

export async function deleteKnowledgeEntry(entryId: string): Promise<KnowledgeEntry> {
  const response = await http.delete(`/api/v1/knowledge/entries/${encodeURIComponent(entryId)}`)
  return unwrap<KnowledgeEntry>(response.data)
}

export async function fetchKnowledgeVersions(entryId: string): Promise<KnowledgeVersion[]> {
  const response = await http.get(`/api/v1/knowledge/entries/${encodeURIComponent(entryId)}/versions`)
  return unwrap<KnowledgeVersion[]>(response.data)
}

export async function fetchKnowledgeLinks(entryId: string): Promise<KnowledgeLinks> {
  const response = await http.get(`/api/v1/knowledge/entries/${encodeURIComponent(entryId)}/links`)
  return unwrap<KnowledgeLinks>(response.data)
}

export async function fetchGuidance(params: {
  caseId?: string
  questionId?: string
  elementKey?: string
  q?: string
  limit?: number
}): Promise<GuidanceItem[]> {
  const response = await http.get('/api/v1/knowledge/guidance/match', { params })
  return unwrap<GuidanceItem[]>(response.data)
}

export async function fetchDraftQuestions(payload: {
  caseId?: string
  questionId?: string
  elementKey?: string
  /** 刚才的回答，让追问跟着回答内容走 */
  q?: string
  limit?: number
}): Promise<DraftQuestion[]> {
  const response = await http.post('/api/v1/knowledge/draft-questions', payload)
  return unwrap<DraftQuestion[]>(response.data)
}

/** 本案模板 / 案由适用的定稿校验规则（知识库条目的「校验项」）。 */
export async function fetchCaseCheckRules(caseId: string): Promise<CaseCheckRules> {
  const response = await http.get('/api/v1/knowledge/check-rules', { params: { caseId } })
  return unwrap<CaseCheckRules>(response.data)
}

export async function runKnowledgeImport(options: { dryRun?: boolean; root?: string } = {}): Promise<ImportReport> {
  const response = await http.post('/api/v1/knowledge/import', {
    dryRun: options.dryRun ?? true,
    ...(options.root ? { root: options.root } : {}),
  })
  return unwrap<ImportReport>(response.data)
}

export async function fetchTermCorrections(active?: boolean): Promise<TermCorrection[]> {
  const response = await http.get('/api/v1/knowledge/term-corrections', {
    params: active === undefined ? undefined : { active },
  })
  return unwrap<TermCorrection[]>(response.data)
}

export async function saveTermCorrection(input: {
  wrong: string
  right: string
  category?: string
  active?: boolean
  replace?: boolean
}): Promise<TermCorrection> {
  const response = await http.post('/api/v1/knowledge/term-corrections', input)
  return unwrap<TermCorrection>(response.data)
}

export async function setTermCorrectionActive(correctionId: string, active: boolean): Promise<TermCorrection> {
  const response = await http.patch(`/api/v1/knowledge/term-corrections/${encodeURIComponent(correctionId)}`, { active })
  return unwrap<TermCorrection>(response.data)
}

/** 对一段识别文本做确定性命中，返回可能出现同音错写的词条（不修改原文）。 */
export async function lookupTermCorrections(text: string): Promise<Array<{ wrong: string; right: string; entryId?: string | null }>> {
  if (!text.trim()) return []
  const response = await http.get('/api/v1/knowledge/term-corrections/lookup', { params: { text: text.slice(0, 2000) } })
  return unwrap<Array<{ wrong: string; right: string; entryId?: string | null }>>(response.data)
}

/** 智能追问：本案某条推荐问法的使用次数（按案件计） */
export interface SuggestionUsage {
  shown: number
  adopted: number
  notApplicable: number
}

export interface Suggestion {
  key: string
  text: string
  elementKey: string | null
  elementLabel: string
  reason: 'ELEMENT' | 'CONTEXT'
  entryId: string
  entryTitle: string
  entryVersion: number
  sourceRef: string | null
  usage: SuggestionUsage
}

export interface SuggestionResult {
  caseId: string
  templateTitle: string
  focus: { elementKey: string; label: string; status: string; statusText: string; hint: string } | null
  pendingElements: Array<{ elementKey: string; label: string }>
  suggestions: Suggestion[]
}

/** 按本案未确认的要素取推荐追问；后端每案每条只记一次展示。 */
export async function fetchSuggestions(payload: { caseId: string; questionId?: string; q?: string; limit?: number }): Promise<SuggestionResult> {
  const response = await http.post('/api/v1/knowledge/suggestions', payload)
  return unwrap<SuggestionResult>(response.data)
}

/** 采纳（后端建一张 LIVE 草稿题）或标为不适用；重复提交不重复计数。 */
export async function sendSuggestionFeedback(payload: { caseId: string; key: string; action: 'ADOPTED' | 'NOT_APPLICABLE' }) {
  const response = await http.post('/api/v1/knowledge/suggestions/feedback', payload)
  return unwrap<{ key: string; decision: string; createdQuestionId: string | null }>(response.data)
}

export async function fetchKnowledgeUsage(): Promise<Record<string, SuggestionUsage>> {
  const response = await http.get('/api/v1/knowledge/usage')
  return unwrap<Record<string, SuggestionUsage>>(response.data)
}

export async function fetchEntryUsage(entryId: string): Promise<Array<SuggestionUsage & { text: string; elementKey: string | null }>> {
  const response = await http.get(`/api/v1/knowledge/entries/${encodeURIComponent(entryId)}/usage`)
  return unwrap<Array<SuggestionUsage & { text: string; elementKey: string | null }>>(response.data)
}

/** 经验提炼（Task 02）：已结案案件中民警补充的问法，规则脱敏后等待人工审核。 */
export type ExperienceStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface ExperienceCandidate {
  id: string
  scopeKey: string
  scopeTitle: string
  templateKey: string | null
  caseType: string | null
  elementKey: string | null
  elementLabel: string
  proposedText: string
  /** 脱敏时替换过的信息类型，如 人名、车牌 */
  maskRules: string[]
  status: ExperienceStatus
  reviewedBy: string | null
  reviewedAt: string | null
  reviewNote: string | null
  publishedText: string | null
  publishedEntryId: string | null
  publishedVersion: number | null
  caseCount: number
  sources: Array<{ caseId: string; questionId: string; originalText: string; harvestedAt: string | null }>
  createdAt: string | null
}

export interface ExperienceScope {
  scopeKey: string
  title: string
  templateKey: string | null
  caseType: string | null
  closedCases: number
  elements: Array<{ key: string; label: string }>
  /** 结案时仍未确认的要素：容易漏问的地方 */
  gaps: Array<{ elementKey: string; label: string; cases: number }>
}

export interface ExperienceOverview {
  counts: Record<ExperienceStatus, number>
  scopes: ExperienceScope[]
  candidates: ExperienceCandidate[]
}

/** 扫描已结案案件提炼候选问法；可重复执行，每道题只提炼一次。 */
export async function harvestExperience(): Promise<{ scannedCases: number; addedSources: number; newCandidates: number }> {
  const response = await http.post('/api/v1/knowledge/experience/harvest')
  return unwrap<{ scannedCases: number; addedSources: number; newCandidates: number }>(response.data)
}

export async function fetchExperience(status?: ExperienceStatus): Promise<ExperienceOverview> {
  const response = await http.get('/api/v1/knowledge/experience', { params: status ? { status } : {} })
  return unwrap<ExperienceOverview>(response.data)
}

/** 审核通过：写进该模板的「办案经验问法」条目（新版本），下一个同类案件即可推荐。 */
export async function approveExperience(candidateId: string, payload: { text: string; elementKey?: string | null; note?: string }) {
  const response = await http.post(`/api/v1/knowledge/experience/${encodeURIComponent(candidateId)}/approve`, payload)
  return unwrap<{ candidate: ExperienceCandidate; entry: KnowledgeEntry }>(response.data)
}

export async function rejectExperience(candidateId: string, note?: string): Promise<ExperienceCandidate> {
  const response = await http.post(`/api/v1/knowledge/experience/${encodeURIComponent(candidateId)}/reject`, { note })
  return unwrap<ExperienceCandidate>(response.data)
}
