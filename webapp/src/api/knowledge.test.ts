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
})
