import { http } from './http'

export interface KnowledgeCategory {
  id: string
  name: string
  active: boolean
}

export type KnowledgeStatus = 'verified' | 'pending'
export type KnowledgeKind = 'faq' | 'wiki'

export interface KnowledgeEntry {
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
  sourceRef?: string | null
  sourceSha256?: string | null
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

export interface TermCorrection {
  id: string
  wrong: string
  right: string
  category: string
  active: boolean
  entryId?: string | null
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
  sourceRef?: string | null
}): Promise<KnowledgeEntry> {
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
    sourceRef: string | null
  }>,
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
  limit?: number
}): Promise<DraftQuestion[]> {
  const response = await http.post('/api/v1/knowledge/draft-questions', payload)
  return unwrap<DraftQuestion[]>(response.data)
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
