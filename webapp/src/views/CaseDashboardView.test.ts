import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import CaseDashboardView from './CaseDashboardView.vue'

describe('CaseDashboardView ledger (design P20)', () => {
  it('shows the ledger title, three filters and the design columns', async () => {
    const html = await renderToString(createSSRApp(CaseDashboardView))
    expect(html).toContain('全部案件记录')
    expect(html).toContain('点击行进入案件详情')
    for (const label of ['关键字', '状态', '主审']) expect(html).toContain(label)
    for (const column of ['案件编号', '案由', '状态', '主审', '更新时间', '操作']) expect(html).toContain(`>${column}</th>`)
    expect(html).toContain('新建询问')
  })

  it('drops the statistics cards and the side column', async () => {
    const html = await renderToString(createSSRApp(CaseDashboardView))
    expect(html).not.toContain('进行中的审讯')
    expect(html).not.toContain('开始前自检')
  })
})
