import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()
const del = vi.fn()

vi.mock('./http', () => ({ http: { get, post, patch, delete: del } }))

const envelope = (data: unknown) => ({ data: { ok: true, code: 'OK', message: 'OK', data } })

describe('knowledge api client', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    patch.mockReset()
    del.mockReset()
  })

  it('maps guidance query parameters and unwraps the envelope', async () => {
    get.mockResolvedValue(envelope([{ id: 'k1', title: '案发时间核对要点' }]))
    const { fetchGuidance } = await import('./knowledge')
    const result = await fetchGuidance({ caseId: 'case-1', questionId: 'q1', elementKey: 'time', limit: 3 })
    expect(get).toHaveBeenCalledWith('/api/v1/knowledge/guidance/match', {
      params: { caseId: 'case-1', questionId: 'q1', elementKey: 'time', limit: 3 },
    })
    expect(result).toEqual([{ id: 'k1', title: '案发时间核对要点' }])
  })

  it('loads the finalize check rules for a case', async () => {
    get.mockResolvedValue(envelope({ caseId: 'case-1', templateKey: 'THEFT_EBIKE_V1', caseType: 'theft', rules: [] }))
    const { fetchCaseCheckRules } = await import('./knowledge')
    const result = await fetchCaseCheckRules('case-1')
    expect(get).toHaveBeenCalledWith('/api/v1/knowledge/check-rules', { params: { caseId: 'case-1' } })
    expect(result.templateKey).toBe('THEFT_EBIKE_V1')
  })

  it('asks for element-driven suggestions and reports adopt / not-applicable feedback', async () => {
    post.mockResolvedValueOnce(envelope({ caseId: 'case-1', templateTitle: '盗窃（电动车）', focus: null, pendingElements: [], suggestions: [] }))
    post.mockResolvedValueOnce(envelope({ key: 'k', decision: 'ADOPTED', createdQuestionId: 'q9' }))
    const { fetchSuggestions, sendSuggestionFeedback } = await import('./knowledge')
    expect((await fetchSuggestions({ caseId: 'case-1', questionId: 'q1', q: '锁了', limit: 3 })).templateTitle).toBe('盗窃（电动车）')
    expect(post).toHaveBeenNthCalledWith(1, '/api/v1/knowledge/suggestions', { caseId: 'case-1', questionId: 'q1', q: '锁了', limit: 3 })
    expect((await sendSuggestionFeedback({ caseId: 'case-1', key: 'k', action: 'ADOPTED' })).createdQuestionId).toBe('q9')
    expect(post).toHaveBeenNthCalledWith(2, '/api/v1/knowledge/suggestions/feedback', { caseId: 'case-1', key: 'k', action: 'ADOPTED' })
  })

  it('loads usage statistics for the admin list and one entry', async () => {
    get.mockResolvedValueOnce(envelope({ e1: { shown: 3, adopted: 1, notApplicable: 1 } }))
    get.mockResolvedValueOnce(envelope([{ text: '停车时车上用了什么锁？', elementKey: 'lock', shown: 3, adopted: 1, notApplicable: 1 }]))
    const { fetchEntryUsage, fetchKnowledgeUsage } = await import('./knowledge')
    expect((await fetchKnowledgeUsage()).e1?.adopted).toBe(1)
    expect(get).toHaveBeenNthCalledWith(1, '/api/v1/knowledge/usage')
    expect((await fetchEntryUsage('e 1'))[0]?.elementKey).toBe('lock')
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/knowledge/entries/e%201/usage')
  })

  it('surfaces backend error messages instead of returning empty data', async () => {
    get.mockResolvedValue({ data: { ok: false, code: 'KNOWLEDGE_ENTRY_NOT_FOUND', message: '知识条目不存在' } })
    const { fetchKnowledgeEntry } = await import('./knowledge')
    await expect(fetchKnowledgeEntry('missing')).rejects.toThrow('知识条目不存在')
  })

  it('defaults the vault import to a dry run and only sends a root when provided', async () => {
    post.mockResolvedValue(envelope({ dryRun: true }))
    const { runKnowledgeImport } = await import('./knowledge')
    await runKnowledgeImport()
    expect(post).toHaveBeenCalledWith('/api/v1/knowledge/import', { dryRun: true })

    post.mockResolvedValue(envelope({ dryRun: false }))
    await runKnowledgeImport({ dryRun: false, root: '/var/lib/suspect-interrogation/knowledge-vault' })
    expect(post).toHaveBeenLastCalledWith('/api/v1/knowledge/import', {
      dryRun: false,
      root: '/var/lib/suspect-interrogation/knowledge-vault',
    })
  })

  it('skips the lookup round trip for blank recognition text', async () => {
    const { lookupTermCorrections } = await import('./knowledge')
    await expect(lookupTermCorrections('   ')).resolves.toEqual([])
    expect(get).not.toHaveBeenCalled()
  })

  it('encodes ids when patching entries and term corrections', async () => {
    patch.mockResolvedValue(envelope({ id: 'a b', version: 2 }))
    const { updateKnowledgeEntry, setTermCorrectionActive } = await import('./knowledge')
    await updateKnowledgeEntry('a b', { status: 'verified' })
    expect(patch).toHaveBeenCalledWith('/api/v1/knowledge/entries/a%20b', { status: 'verified' })

    await setTermCorrectionActive('c/d', false)
    expect(patch).toHaveBeenLastCalledWith('/api/v1/knowledge/term-corrections/c%2Fd', { active: false })
  })

  it('formats a verifiable citation and falls back to the original file path', async () => {
    const { formatCitation, formatEffectivePeriod } = await import('./knowledge')
    expect(formatCitation({
      sourceDocument: '治安管理处罚法', sourceLocator: '第四十九条', sourceVersion: '2012 修正', sourceRef: 'raw/a.pdf',
    })).toBe('《治安管理处罚法》第四十九条（2012 修正）')
    expect(formatCitation({ sourceDocument: '《接警记录规范》' })).toBe('《接警记录规范》')
    expect(formatCitation({ sourceLocator: 'p.12' })).toBe('p.12')
    expect(formatCitation({ sourceRef: 'raw/接警记录规范.md#时间' })).toBe('raw/接警记录规范.md#时间')
    expect(formatCitation({})).toBe('')
    expect(formatEffectivePeriod({ effectiveFrom: '2013-01-01', effectiveUntil: '2026-01-01' }))
      .toBe('2013-01-01 起施行 · 2026-01-01 起失效')
    expect(formatEffectivePeriod({})).toBe('')
  })

  it('sends citation fields when creating an entry', async () => {
    post.mockResolvedValue(envelope({ id: 'k1' }))
    const { createKnowledgeEntry } = await import('./knowledge')
    await createKnowledgeEntry({
      title: '盗窃处罚', categoryId: 'law', content: '正文',
      sourceDocument: '治安管理处罚法', sourceLocator: '第四十九条', effectiveFrom: '2013-01-01', supersededById: null,
    })
    expect(post).toHaveBeenCalledWith('/api/v1/knowledge/entries', {
      title: '盗窃处罚', categoryId: 'law', content: '正文',
      sourceDocument: '治安管理处罚法', sourceLocator: '第四十九条', effectiveFrom: '2013-01-01', supersededById: null,
    })
  })
  it('harvests closed-case experience and sends approve / reject decisions', async () => {
    post.mockResolvedValueOnce(envelope({ scannedCases: 3, addedSources: 2, newCandidates: 1 }))
    get.mockResolvedValueOnce(envelope({ counts: { PENDING: 1, APPROVED: 0, REJECTED: 0 }, scopes: [], candidates: [] }))
    post.mockResolvedValueOnce(envelope({ candidate: { id: 'c1' }, entry: { id: 'k9', version: 2 } }))
    post.mockResolvedValueOnce(envelope({ id: 'c2', status: 'REJECTED' }))
    const { approveExperience, fetchExperience, harvestExperience, rejectExperience } = await import('./knowledge')
    expect((await harvestExperience()).newCandidates).toBe(1)
    expect(post).toHaveBeenLastCalledWith('/api/v1/knowledge/experience/harvest')
    await fetchExperience('PENDING')
    expect(get).toHaveBeenCalledWith('/api/v1/knowledge/experience', { params: { status: 'PENDING' } })
    const approved = await approveExperience('c1', { text: '你停车时旁边有没有其他电动车？', elementKey: 'witness' })
    expect(post).toHaveBeenLastCalledWith('/api/v1/knowledge/experience/c1/approve', { text: '你停车时旁边有没有其他电动车？', elementKey: 'witness' })
    expect(approved.entry.version).toBe(2)
    await rejectExperience('c2', '与案件无关')
    expect(post).toHaveBeenLastCalledWith('/api/v1/knowledge/experience/c2/reject', { note: '与案件无关' })
  })
})
