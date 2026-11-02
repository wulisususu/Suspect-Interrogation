import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import RecordReviewPanel from './RecordReviewPanel.vue'

const fragment = {
  id: 'f1', ordinal: 1, captureSessionId: 'c1', startedAtMs: 65_000, endedAtMs: 68_000,
  rawText: '我当时在单元门口', editedText: '', speaker: 'UNKNOWN', speakerSource: 'PENDING_ANALYSIS',
  confidence: 0.92, confidenceSource: 'ASR', state: 'PENDING', confirmedMessageId: null, recognitionRevisions: [],
}
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(RecordReviewPanel, {
  fragments: [fragment], qaUnits: [], busy: false, frozen: false, ...props,
}))

describe('RecordReviewPanel (定稿校验 · 去处理弹窗)', () => {
  it('no longer shows speaker attribution now that voiceprints are retired', async () => {
    const html = await render()
    expect(html).toContain('我当时在单元门口')
    expect(html).not.toContain('说话人')
    expect(html).not.toContain('嫌疑人')
    expect(html).not.toContain('<select')
  })

  it('drops the 选入笔录 shortcut, which has no drop target on the review page', async () => {
    const html = await render()
    expect(html).not.toContain('选入笔录')
    expect(html).toContain('确认转写')
    expect(html).toContain('返回修改')
  })

  it('offers a direct discard on every unconfirmed fragment', async () => {
    expect(await render()).toContain('丢弃此段</button>')
    expect(await render({ fragments: [{ ...fragment, state: 'CONFIRMED', confirmedMessageId: 'm1' }] })).not.toContain('丢弃此段</button>')
  })
})
