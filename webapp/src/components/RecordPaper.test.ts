import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import RecordPaper from './RecordPaper.vue'

describe('RecordPaper', () => {
  it('prints the current address fact, not the ID-card address, under 现住址', async () => {
    const html = await renderToString(createSSRApp(RecordPaper, {
      summary: { id: 'C', suspectName: '王某某', address: '身份证上的地址', state: 'DRAFT', stage: 'IDENTITY' },
      facts: [{ key: 'current_address', label: '现住址', value: '现在住的地方', status: 'confirmed' }],
      session: { id: 's', caseId: 'C', status: 'READY', stage: 'IDENTITY', startedAt: null, endedAt: null, pausedAt: null, updatedAt: 1 },
      questions: [],
    }))
    expect(html).toContain('现住址：现在住的地方')
    expect(html).not.toContain('身份证上的地址')
  })
})
