import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import CaseProfilePage from './CaseProfilePage.vue'

const summary = {
  id: 'CASE-UI', suspectName: '王某某', gender: '女', nation: '汉', birthDate: '1992-05-14', age: '',
  idNumber: '110101199205140000', address: '测试路 1 号', officerName: '张伟', state: 'DRAFT', stage: 'IDENTITY',
}
const facts = [
  { key: 'contact', label: '联系方式', value: '13800000000', status: 'confirmed' },
  { key: 'current_address', label: '现住址', value: '测试路 1 号', status: 'confirmed' },
]
const render = (identitySource: string, locked = false) => renderToString(createSSRApp(CaseProfilePage, { summary: { ...summary, identitySource }, facts, locked }))

describe('CaseProfilePage (design P06)', () => {
  it('marks manually entered identity fields as 手工补填', async () => {
    const html = await render('MANUAL')
    expect(html).toContain('被询问人身份信息')
    expect(html).toContain('手工补填')
    expect(html).not.toContain('身份证读取</span>')
  })

  it('marks card-read fields with their source', async () => {
    const html = await render('ID_CARD_READER')
    expect(html).toContain('身份证读取</span>')
  })

  it('offers save-draft and next-step actions in the page header', async () => {
    const html = await render('MANUAL')
    expect(html).toContain('暂存草稿')
    expect(html).toContain('下一步 · 问答录入')
  })

  it('shows the intake completeness bar', async () => {
    const html = await render('MANUAL')
    expect(html).toMatch(/建档核对[\s\S]*信息完整度 75%/)
  })

  it('is read-only once the record is frozen', async () => {
    const html = await render('MANUAL', true)
    const inputs = html.match(/<(input|select)\b[^>]*>/g) ?? []
    expect(inputs.length).toBeGreaterThan(0)
    for (const input of inputs) expect(input).toMatch(/disabled|readonly/)
    expect(html).toMatch(/<button[^>]*disabled[^>]*>暂存草稿/)
    expect(html).toContain('笔录已冻结，身份信息只读')
  })
})
