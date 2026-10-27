import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import CaseDetailContent from './CaseDetailContent.vue'

const base = {
  summary: { id: 'CASE-UI', suspectName: '王某某', gender: '女', idNumber: '110101199205140000', officerName: '张伟', caseType: 'suspect_interrogation', state: 'DRAFT', stage: 'IDENTITY', workflowState: 'SUMMARY', updatedAt: 5 },
  facts: [{ key: 'time', label: '时间', value: '上午', status: 'confirmed' }, { key: 'place', label: '地点', value: '', status: 'missing' }],
  session: { id: 's', caseId: 'CASE-UI', status: 'COMPLETED', stage: 'SIGNING', startedAt: 1, endedAt: 2, pausedAt: null, updatedAt: 2 },
  questions: [{ id: 'q', text: '请讲一下经过？', formalAnswerText: '当天在家', sortOrder: 1 }],
  signingState: null,
}
const render = (patch: Record<string, unknown> = {}) => renderToString(createSSRApp(CaseDetailContent, { ...base, ...patch }))

describe('CaseDetailContent (design P21–P22)', () => {
  it('collects record info, element coverage, recordings and the document preview', async () => {
    const html = await render()
    expect(html).toContain('笔录与卷宗信息')
    expect(html).toContain('要素覆盖 1 / 2')
    expect(html).toContain('时间')
    expect(html).toContain('录音')
    expect(html).toContain('功能待接入')
    expect(html).toContain('文书预览')
    expect(html).toContain('请讲一下经过？')
  })

  it('lets unarchived cases continue and lists their missing elements', async () => {
    const html = await render()
    expect(html).toContain('继续办理')
    expect(html).toMatch(/缺项[\s\S]*地点/)
  })

  it('keeps archived cases read-only', async () => {
    const html = await render({ summary: { ...base.summary, workflowState: 'REPORT_GENERATED' } })
    expect(html).not.toContain('继续办理')
    expect(html).toContain('笔录只读')
  })
})
