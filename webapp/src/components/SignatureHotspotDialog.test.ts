import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import SignatureHotspotDialog from './SignatureHotspotDialog.vue'

const render = (props: Record<string, unknown>) => renderToString(createSSRApp(SignatureHotspotDialog, { officers: [], busy: false, ...props }))

describe('SignatureHotspotDialog (design P14)', () => {
  it('shows the fingerprint capture window and keeps confirm disabled without a reader', async () => {
    const html = await render({ role: 'FINGERPRINT' })
    expect(html).toContain('指纹捺印 · 现场采集')
    expect(html).toContain('0 / 1 枚 · 请按压采集窗')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>确认捺印并写入/)
    expect(html).toContain('未接入采集器')
  })

  it('lists officers for preset signatures and falls back to handwriting', async () => {
    const html = await render({ role: 'OFFICER', officers: [{ officerId: '038291', officerName: '张伟' }, { officerId: '036612', officerName: '刘敏' }] })
    expect(html).toContain('民警签名 · 预录入调用')
    expect(html).toContain('张伟（038291）')
    expect(html).toContain('刘敏（036612）')
    expect(html).toContain('未预录入签名')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>确认调用并写入/)
    expect(html).toContain('改为现场手写')
  })

  it('explains when no officer is on file', async () => {
    expect(await render({ role: 'OFFICER' })).toContain('民警声纹库中暂无民警')
  })
})
