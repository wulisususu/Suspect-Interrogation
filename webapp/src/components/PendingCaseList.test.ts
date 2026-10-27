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
})
