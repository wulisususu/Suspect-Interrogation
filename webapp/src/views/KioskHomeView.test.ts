import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import KioskHomeView from './KioskHomeView.vue'

describe('KioskHomeView (design P04)', () => {
  it('offers the manual mode entry with its three-step flow and no self-service card', async () => {
    const html = await renderToString(createSSRApp(KioskHomeView))
    expect(html).toContain('人工模式')
    expect(html).toContain('民警办理')
    for (const step of ['选模板建档', '问答与定稿', '签署打印']) expect(html).toContain(step)
    expect(html).toContain('开始新建笔录')
    expect(html).not.toContain('自助模式')
  })

  it('closes with the compliance, privacy and device strip', async () => {
    const html = await renderToString(createSSRApp(KioskHomeView))
    expect(html).toContain('合规：民警在场确认后定稿')
    expect(html).toContain('隐私：全程保密，仅用于本次办理')
    expect(html).toContain('设备：')
  })
})
