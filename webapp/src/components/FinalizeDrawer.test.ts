import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import { finalizeChecks } from '../utils/reviewChecks'
import FinalizeDrawer from './FinalizeDrawer.vue'
import pageSource from './TemplateDrivenInterrogationPage.vue?raw'

const checks = finalizeChecks({
  summary: { suspectName: '王某某', idNumber: '330501199205142319' },
  templateTitle: '盗窃（电动车）',
  autoChecks: [
    { key: 'elements', title: '模板要素', state: 'pass', detail: '要素 6/6 已覆盖' },
    { key: 'timeline', title: '时间线一致', state: 'unavailable', detail: '' },
    { key: 'signers', title: '签署人数与身份', state: 'pending', detail: '记录人 未填写' },
  ],
  draftAnswers: 0, unresolvedFragments: 0, unresolvedQa: 0,
})
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(FinalizeDrawer, {
  checks, coverage: { covered: 6, total: 6 }, blockReason: '', busy: false, ...props,
}))

describe('FinalizeDrawer (design P08 · state C)', () => {
  it('summarises the checks as pass / pending blocks and hides unimplemented ones', async () => {
    const html = await render()
    expect(html).toContain('定稿前校验 · 逐项确认（只提示，不代改）')
    expect(html).toContain('4 项检查 · 3 项通过 · 1 项待确认')
    expect(html).toContain('通过 · 模板要素')
    expect(html).toContain('待确认 · 签署人数与身份')
    expect(html).not.toContain('时间线一致')
    expect(html).toContain('要素 6/6 已覆盖')
  })

  it('confirms by long press and disables only on a hard block', async () => {
    expect(await render()).toContain('确认定稿 · 正本冻结并进入签署（长按 0.8 秒）')
    const blocked = await render({ blockReason: '还有 2 条转写片段待确认或丢弃' })
    expect(blocked).toContain('还有 2 条转写片段待确认或丢弃')
    expect(blocked).toMatch(/<button[^>]*class="long-press[^"]*finalize-confirm[^"]*"[^>]*disabled/)
  })

  it('opens from the ③ header and 补齐缺项 jumps back to the cards instead of leaving the page', () => {
    expect(pageSource).toContain('@click="drawerOpen = true"')
    expect(pageSource).toContain('@fill="focusMissingCard"')
    expect(pageSource).toContain('<FinalizeDrawer')
  })
})
