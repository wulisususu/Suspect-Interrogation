import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import KioskPendingBanner from './KioskPendingBanner.vue'

describe('KioskPendingBanner', () => {
  it('shows only the count and asks for verification before details', async () => {
    const html = await renderToString(createSSRApp(KioskPendingBanner, { count: 3 }))
    expect(html).toContain('有 3 项未完成办理')
    expect(html).toContain('仅显示条数，验证后展开详情')
    expect(html).toMatch(/<button[^>]*>[\s\S]*验证并继续/)
  })
})
