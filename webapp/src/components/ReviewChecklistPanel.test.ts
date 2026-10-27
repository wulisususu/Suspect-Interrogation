import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ReviewChecklistPanel from './ReviewChecklistPanel.vue'

const autoChecks = [
  { key: 'elements', title: '模板要素', state: 'pass', detail: '要素 6/6 已覆盖' },
  { key: 'timeline', title: '时间线一致', state: 'unavailable', detail: '' },
  { key: 'homophone', title: '同音字纠错', state: 'unavailable', detail: '' },
  { key: 'signers', title: '签署人数与身份', state: 'pending', detail: '民警未绑定' },
]
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(ReviewChecklistPanel, {
  facts: [], questions: [], checks: [false, false, false, false, false], blockReason: '', busy: false, frozen: false,
  unresolvedFragments: 0, unresolvedQa: 0, autoChecks, ...props,
}))

describe('ReviewChecklistPanel (design P12–P13)', () => {
  it('shows the automatic checks with a summary count', async () => {
    const html = await render()
    expect(html).toContain('4 项检查 · 1 项通过 · 1 项待确认')
    for (const title of ['模板要素', '时间线一致', '同音字纠错', '签署人数与身份']) expect(html).toContain(title)
    expect(html).toContain('待接入')
  })

  it('keeps the officer confirmations under their own heading', async () => {
    expect(await render()).toContain('民警确认')
  })

  it('finalises through a long press', async () => {
    expect(await render()).toContain('确认定稿 · 正本冻结并进入签署（长按 800ms）')
  })
})
