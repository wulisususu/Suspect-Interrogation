import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import RecordSigningPage from './RecordSigningPage.vue'

const base = {
  summary: { id: 'UI-ONLY', suspectName: '测试人员', officerName: '测试民警', stage: 'SIGNING', state: 'DRAFT' },
  facts: [],
  session: { id: 's', caseId: 'UI-ONLY', status: 'COMPLETED', stage: 'SIGNING', startedAt: 1, endedAt: 1000, pausedAt: null, updatedAt: 1000 },
  questions: [{ id: 'q', text: '测试问题', formalAnswerText: '完整回答第一行\n完整回答第二行', sortOrder: 1 }],
  signingState: null,
  busy: false,
}
async function screen(overrides = {}) { return renderToString(createSSRApp(RecordSigningPage, { ...base, ...overrides } as any)) }

const frozen = {
  caseId: 'UI-ONLY', version: 2, documentId: 'doc', documentHash: 'real-hash',
  status: 'FROZEN', createdAt: 1000, integrityValid: true, signatures: [],
}

describe('signing and archive UI state', () => {
  it('renders the document with the three inline signature hotspots', async () => {
    const html = await screen({ signingState: frozen })
    expect(html).toContain('完整回答第一行\n完整回答第二行')
    expect(html).toContain('被询问人签名')
    expect(html).toContain('指纹捺印')
    expect(html).toContain('民警签名')
    expect(html).toContain('未接入采集器')
    expect(html).not.toContain('打印成功')
  })

  it('keeps archiving blocked until both signatures are collected', async () => {
    const html = await screen({ signingState: frozen })
    const archiveTag = html.match(/<button[^>]*class="signing-primary"[^>]*>/)?.[0]
    expect(archiveTag).toBeDefined()
    expect(archiveTag).toContain('disabled')
    expect(html).toContain('签名齐备后可归档')
  })

  it('enables archiving once suspect and officer signatures both exist', async () => {
    const signed = {
      ...frozen,
      signatures: [
        { signerRole: 'SUSPECT', signerName: '测试人员', signedAt: 2, imageDataUrl: 'data:,' },
        { signerRole: 'OFFICER', signerName: '测试民警', signedAt: 3, imageDataUrl: 'data:,' },
      ],
    }
    const html = await screen({ signingState: signed })
    const archiveTag = html.match(/<button[^>]*class="signing-primary"[^>]*>/)?.[0]
    expect(archiveTag).not.toContain('disabled')
    expect(html).toContain('确认归档并结案')
    expect(html).toContain('2 / 2 处')
  })

  it('blocks official print when the frozen document fails integrity validation', async () => {
    const broken = { ...frozen, integrityValid: false }
    const html = await screen({ signingState: broken })
    expect(html).toContain('异常')
    const printTag = html.match(/<button[^>]*class="signing-secondary"[^>]*>/)?.[0]
    expect(printTag).toContain('disabled')
    expect(html).toContain('签名完成后可打印')
  })
})
