import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import AuditLogTable from './AuditLogTable.vue'

describe('AuditLogTable (design P29)', () => {
  it('asks to choose a case before showing entries', async () => {
    const html = await renderToString(createSSRApp(AuditLogTable, { entries: [], caseSelected: false }))
    expect(html).toContain('请选择案件查看操作日志')
  })

  it('renders entries read-only with time, operator, action and target', async () => {
    const entries = [{ id: '1', action: 'CASE_CREATE', targetType: 'CASE', targetId: 'C-1', actorId: '张伟', createdAt: Date.UTC(2026, 9, 26, 3, 2) }]
    const html = await renderToString(createSSRApp(AuditLogTable, { entries, caseSelected: true }))
    for (const column of ['时间', '操作人', '动作', '对象']) expect(html).toContain(`>${column}</th>`)
    expect(html).toContain('建案')
    expect(html).toContain('张伟')
    expect(html).toContain('只读留置，不可删除')
    expect(html).not.toMatch(/<button[^>]*>删除/)
  })
})
