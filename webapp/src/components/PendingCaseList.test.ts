import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import PendingCaseList from './PendingCaseList.vue'

const c = (id: string, workflowState: string, state = 'DRAFT') => ({ id, workflowState, state, suspectName: `嫌疑人${id}`, officerName: '张伟', updatedAt: 1 })

describe('PendingCaseList (design P23)', () => {
  it('lists only started, unarchived cases with a continue action', async () => {
    const cases = [c('A', 'IDENTITY_READY'), c('B', 'QUESTIONING', 'INTERROGATING'), c('C', 'FROZEN', 'SIGNING'), c('D', 'INIT'), c('E', 'REPORT_GENERATED', 'COMPLETED')]
    const html = await renderToString(createSSRApp(PendingCaseList, { cases }))
    expect(html).toContain('未完成办理 · 共 3 项')
    expect(html).toContain('案 A')
    expect(html).toContain('案 C')
    expect(html).not.toContain('案 D')
    expect(html).not.toContain('案 E')
    expect(html.match(/继续办理/g)?.length).toBe(3)
  })

  it('shows an empty state when nothing is pending', async () => {
    const html = await renderToString(createSSRApp(PendingCaseList, { cases: [] }))
    expect(html).toContain('暂无未完成办理')
  })

  it('renders the design table with honest interruption reason and the shared status colours (audit D14 / D15 / D33)', async () => {
    const html = await renderToString(createSSRApp(PendingCaseList, { cases: [c('B', 'QUESTIONING', 'INTERROGATING')] }))
    for (const column of ['中断事由', '案件', '最后更新时间', '当前状态', '操作']) expect(html).toMatch(new RegExp(`<th[^>]*>${column}</th>`))
    expect(html).toContain('未记录')
    expect(html).toMatch(/class="(?=[^"]*\bcase-status\b)(?=[^"]*\bis-in_progress\b)[^"]*"[^>]*>进行中/)
  })

  it('pages long lists ten at a time', async () => {
    const cases = Array.from({ length: 23 }, (_, index) => c(`P${index}`, 'QUESTIONING', 'INTERROGATING'))
    const html = await renderToString(createSSRApp(PendingCaseList, { cases }))
    expect(html.match(/继续办理/g)?.length).toBe(10)
    expect(html).toContain('1 / 3')
  })
})
