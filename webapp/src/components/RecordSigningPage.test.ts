import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import RecordSigningPage from './RecordSigningPage.vue'

const base = {
  summary: { id: 'UI-ONLY', suspectName: '测试人员', officerName: '测试民警', stage: 'SIGNING', state: 'DRAFT' },
  facts: [], session: { id: 's', caseId: 'UI-ONLY', status: 'COMPLETED', stage: 'SIGNING', startedAt: 1, endedAt: 1000, pausedAt: null, updatedAt: 1000 },
  questions: [{ id: 'q', text: '测试问题', formalAnswerText: '完整回答第一行\n完整回答第二行', sortOrder: 1 }],
  signingState: null, busy: false, checks: [false, false, false, false, false], blockReason: '请逐项完成打印前核对',
}
async function screen(overrides = {}) { return renderToString(createSSRApp(RecordSigningPage, { ...base, ...overrides } as any)) }

describe('signing and print UI state', () => {
  it('renders actual canonical text and requires all manual checks without claiming print success', async () => {
    const html = await screen()
    expect(html).toContain('完整回答第一行\n完整回答第二行')
    expect(html).toContain('还有 5 项未核对')
    expect(html).toMatch(/class="primary freeze-button" disabled/)
    expect(html).toContain('需在打印机确认')
    expect(html).not.toContain('打印成功')
  })
  it('enables freeze only when the parent guard permits it', async () => {
    const html = await screen({ checks: [true, true, true, true, true], blockReason: '' })
    const freezeTag = html.match(/<button class="primary freeze-button"[^>]*>/)?.[0]
    expect(freezeTag).toBeDefined()
    expect(freezeTag).not.toContain('disabled')
  })
  it('disables official print and signatures when a frozen document fails integrity validation', async () => {
    const html = await screen({ signingState: { version: 2, status: 'FROZEN', integrityValid: false, signatures: [], documentHash: 'real-hash' }, blockReason: '已冻结' })
    expect(html).toContain('完整性校验异常')
    expect(html).toMatch(/class="primary print-button" disabled/)
    expect(html).not.toContain('已签名')
  })
})
