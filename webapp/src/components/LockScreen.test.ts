import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import appSource from '../App.vue?raw'
import LockScreen from './LockScreen.vue'

describe('LockScreen (design P34)', () => {
  it('covers the screen and only offers police verification to unlock', async () => {
    const html = await renderToString(createSSRApp(LockScreen))
    expect(html).toContain('面板已锁定')
    expect(html).toContain('民警验证解锁')
    expect(html).toContain('role="dialog"')
  })

  it('removes business content from the page while locked', () => {
    expect(appSource).toContain('<LockScreen v-if="locked"')
    expect(appSource).toContain('<MaintenanceGate v-else>')
  })
})
