import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import KioskHomeView from './KioskHomeView.vue'
import source from './KioskHomeView.vue?raw'

describe('KioskHomeView (design P04)', () => {
  it('offers manual mode on the left and self-service mode on the right', async () => {
    const html = await renderToString(createSSRApp(KioskHomeView))
    expect(html.indexOf('人工模式')).toBeGreaterThan(-1)
    expect(html.indexOf('自助模式')).toBeGreaterThan(html.indexOf('人工模式'))
    expect(html).toContain('民警办理')
    expect(html).toContain('本人作答')
    for (const step of ['选模板建档', '问答与定稿', '签署打印', '民警建档', '本人作答', '民警定稿']) expect(html).toContain(step)
    expect(html).toContain('开始新建笔录')
    expect(html).toContain('进入自助模式')
    // 设备自检不再占一整张卡片，收在底部状态条
    expect(html).not.toContain('kiosk-devices')
  })

  it('sends every entry through the officer login with its target', () => {
    expect(source).toContain("emit('enter', 'manual')")
    expect(source).toContain("emit('enter', 'self')")
    expect(source).toContain("emit('enter', 'admin')")
    expect(source).not.toContain('policeEntry')
  })

  it('closes with the compliance, privacy and device strip', async () => {
    const html = await renderToString(createSSRApp(KioskHomeView))
    expect(html).toContain('合规：民警在场确认后定稿')
    expect(html).toContain('隐私：全程保密，仅用于本次办理')
    expect(html).toContain('设备：')
    expect(html).toContain('重新自检')
  })
})
