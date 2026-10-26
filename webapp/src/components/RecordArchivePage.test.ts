import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import RecordArchivePage from './RecordArchivePage.vue'

const signingState = {
  caseId: 'CASE-UI', version: 2, documentId: 'doc', documentHash: 'h', status: 'LOCKED', createdAt: 1, integrityValid: true,
  signatures: [
    { signerRole: 'SUSPECT', signerName: '王某某', signedAt: 2, imageDataUrl: 'data:,' },
    { signerRole: 'OFFICER', signerName: '张伟', signedAt: 3, imageDataUrl: 'data:,' },
  ],
}
const render = () => renderToString(createSSRApp(RecordArchivePage, {
  summary: { id: 'CASE-UI', suspectName: '王某某', officerName: '张伟', state: 'COMPLETED', stage: 'SIGNING', updatedAt: 5 },
  facts: [{ key: 'time', label: '时间', value: '上午', status: 'confirmed' }, { key: 'place', label: '地点', value: '', status: 'missing' }],
  session: { id: 's', caseId: 'CASE-UI', status: 'COMPLETED', stage: 'SIGNING', startedAt: 1, endedAt: 2, pausedAt: null, updatedAt: 2 },
  questions: [{ id: 'q', text: '问题', formalAnswerText: '回答', sortOrder: 1 }],
  signingState,
}))

describe('RecordArchivePage (design P16)', () => {
  it('leads with the archive result card and four fact tiles', async () => {
    const html = await render()
    expect(html).toContain('归档成功 · 办结')
    expect(html).toContain('要素 1/2 覆盖')
    for (const tile of ['卷　号', '归档人 · 时间', '签　章', '录音 · 文书']) expect(html).toContain(tile)
    expect(html).toContain('签名 2 处')
  })

  it('offers Word and PDF exports as two cards with three notes each', async () => {
    const html = await render()
    for (const card of ['导出 Word', '导出 PDF']) {
      const start = html.indexOf(`>${card}</h2>`)
      expect(start).toBeGreaterThan(0)
      const section = html.slice(start, html.indexOf('</section>', start))
      expect(section.match(/<li/g)?.length).toBe(3)
    }
  })

  it('says the volume number is pending when no prefix is configured', async () => {
    expect(await render()).toContain('卷号待分配')
  })
})
