import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import RecordPaper from './RecordPaper.vue'
import source from './RecordPaper.vue?raw'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const session = { id: 's', caseId: 'C', status: 'READY', stage: 'IDENTITY', startedAt: null, endedAt: null, pausedAt: null, updatedAt: 1 }
const summary = { id: 'C', suspectName: '王某某', address: '身份证上的地址', state: 'DRAFT', stage: 'IDENTITY', officerName: '张伟', gender: '男', birthDate: '1990-03-05', idNumber: '320602199003051234' }
const fact = (key: string, value: string) => ({ key, label: key, value, status: 'confirmed' })
const question = (id: string, text: string, answer: string, sortOrder: number) => ({ id, text, formalAnswerText: answer, sortOrder, active: true, rounds: [] })

const render = (props: Record<string, unknown>, footer = false) => renderToString(createSSRApp({
  render: () => h(RecordPaper, { summary, facts: [], session, questions: [], ...props }, footer ? { footer: () => h('div', { class: 'sig' }, '被询问人签名：') } : undefined),
}))

describe('RecordPaper (police print format)', () => {
  it('prints the current address fact, not the ID-card address, under 现住址', async () => {
    const html = await render({ facts: [fact('current_address', '现在住的地方')] })
    expect(html).toMatch(/现住址<\/span><span class="is-grow record-value"[^>]*>现在住的地方</)
    expect(html).not.toContain('身份证上的地址')
  })

  it('lays out the header like the station form: round, title, underlined fields', async () => {
    const html = await render({ facts: [fact('interrogation_round', '1'), fact('officer_unit', '某市公安局某派出所'), fact('peoples_representative', '否')] })
    expect(html).toContain('第<span data-v-')
    expect(html).toMatch(/<h2[^>]*>询问笔录<\/h2>/)
    for (const label of ['时间', '地点', '询问人', '记录人', '工作单位', '被询问人', '身份证件种类及号码', '性别', '出生日期', '人大代表', '联系方式', '现住址', '户籍所在地']) {
      expect(html).toContain(`>${label}</span>`)
    }
    expect(html).toContain('身份证，320602199003051234')
    expect(html).toContain('1990年3月5日')
    expect(html).toContain('>张伟</span>')
    expect(html).toContain('>某市公安局某派出所</span>')
    // 空栏目留空白下划线，不印「未填写」
    expect(html).not.toContain('未填写')
  })

  it('numbers every page as 第N页，共M页 and moves the signature block to a new page when it does not fit', async () => {
    const long = Array.from({ length: 12 }, (_, index) => question(`q${index}`, `第${index + 1}个问题？`, '回答。', index))
    const html = await render({ questions: long }, true)
    const pages = html.match(/class="record-sheet"/g)?.length ?? 0
    expect(pages).toBe(2)
    expect(html).toContain('第1页，共2页')
    expect(html).toContain('第2页，共2页')
    expect(html.match(/class="sig"/g)).toHaveLength(1)
  })

  it('skips removed questions and prints unanswered ones as /', async () => {
    const html = await render({ questions: [question('a', '你叫什么？', '', 1), { ...question('b', '已删除的题', '', 2), active: false }] })
    expect(html).toContain('答：/')
    expect(html).not.toContain('已删除的题')
  })

  it('uses the Song typeface, black ink and a zero-margin A4 page for print', () => {
    const tokens = readFileSync(join(__dirname, '../styles/tokens.css'), 'utf8')
    expect(tokens).toMatch(/--record-ink:\s*#000000/)
    expect(tokens).toMatch(/--font-record:\s*"SimSun", "宋体"/)
    expect(source).toContain('font-family: var(--font-record)')
    expect(source).toContain('@page { size: A4; margin: 0; }')
    expect(source).toMatch(/width: 210mm; height: 297mm/)
  })
})
