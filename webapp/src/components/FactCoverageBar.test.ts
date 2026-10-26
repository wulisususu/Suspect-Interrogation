import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import FactCoverageBar from './FactCoverageBar.vue'

const fact = (key: string, label: string, status: string) => ({ key, label, value: '', status })
const facts = [
  fact('time', '时间', 'confirmed'), fact('place', '地点', 'confirmed'), fact('motive', '动机', 'confirmed'),
  fact('method', '手段', 'confirmed'), fact('process', '经过', 'pending'), fact('evidence', '证据', 'missing'), fact('after', '后果', 'missing'),
]

describe('FactCoverageBar (design P08)', () => {
  it('summarises element coverage and shows at most three missing chips', async () => {
    const html = await renderToString(createSSRApp(FactCoverageBar, { facts }))
    expect(html).toContain('依据模板 · 7 项要素 · 已覆盖 4/7')
    expect(html).toContain('经过')
    expect(html).toContain('证据')
    expect(html).toContain('后果')
    expect(html).toContain('补齐缺项')
  })

  it('collapses extra missing elements into a counter', async () => {
    const html = await renderToString(createSSRApp(FactCoverageBar, { facts: facts.map((item) => ({ ...item, status: 'missing' })) }))
    expect(html).toContain('+4')
  })
})
