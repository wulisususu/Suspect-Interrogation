import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import AdminPlaceholderView from './AdminPlaceholderView.vue'
import RecordingPlayerShell from '../components/RecordingPlayerShell.vue'
import SignatureEnrollDialog from '../components/SignatureEnrollDialog.vue'

const render = (kind: string) => renderToString(createSSRApp(AdminPlaceholderView, { kind }))

describe('AdminPlaceholderView (design P24–P28)', () => {
  it.each([
    ['knowledge', '知识库管理', ['条目标题', '分类', '状态', '更新时间', '操作'], '问话要点'],
    ['templates', '模板管理', ['模板名称', '案件类型', '版本', '状态', '更新时间'], ''],
    ['signatures', '民警签名管理（预先录入）', ['民警', '警号', '签名样式', '录入时间', '状态'], ''],
  ])('renders the %s list skeleton with a pending body', async (kind, title, columns, category) => {
    const html = await render(kind)
    expect(html).toContain(title)
    for (const column of columns) expect(html).toContain(`>${column}</th>`)
    if (category) expect(html).toContain(category)
    expect(html).toContain('功能待接入')
  })

  it('renders the template editor as tree and live preview panes', async () => {
    const html = await render('template-edit')
    expect(html).toContain('模板编辑')
    expect(html).toContain('结构树')
    expect(html).toContain('实时预览')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>保存为新版本/)
  })

  it('renders both recording channels with the player shell', async () => {
    const html = await render('recordings')
    expect(html).toContain('录音查看 · 双通道双文件')
    expect(html).toContain('通道① 问答分段录音')
    expect(html).toContain('通道② 全程录音（原始文件）')
    expect(html).toContain('倍速')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>调阅全程录音/)
  })

  it('opens the signature enrolment shell from 新增签名', async () => {
    const html = await render('signatures')
    expect(html).toMatch(/<button(?![^>]*disabled)[^>]*>＋ 新增签名/)
  })

  it('keeps create actions without a dialog disabled', async () => {
    for (const kind of ['knowledge', 'templates']) {
      const html = await render(kind)
      expect(html).toMatch(/<button[^>]*disabled[^>]*title="功能待接入"[^>]*>(?:(?!<\/button>)[\s\S])*新/)
    }
  })
})

describe('P32 shells', () => {
  it('shows the signature enrolment dialog with disabled confirm', async () => {
    const html = await renderToString(createSSRApp(SignatureEnrollDialog))
    expect(html).toContain('新增 / 更换民警签名')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>保存签名/)
  })

  it('shows the player with progress, speed and timestamp jump', async () => {
    const html = await renderToString(createSSRApp(RecordingPlayerShell))
    expect(html).toContain('00:00 / 00:00')
    expect(html).toContain('1.0×')
    expect(html).toMatch(/<button(?=[^>]*disabled)(?=[^>]*aria-label="播放")[^>]*>/)
  })
})
