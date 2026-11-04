import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import AdminShell from '../components/AdminShell.vue'
import AdminPanelView from './AdminPanelView.vue'
import adminPanelSource from './AdminPanelView.vue?raw'
import knowledgeSource from './KnowledgeAdminView.vue?raw'
import LoginView from './LoginView.vue'

describe('admin shell (design P19 top bar)', () => {
  it('names the back-office, shows the session state placeholder and offers manual lock', async () => {
    const html = await renderToString(createSSRApp({ render: () => h(AdminShell, { title: '管理面板' }, { default: () => '内容' }) }))
    expect(html).toContain('公安笔录一体机 · 后台管理')
    expect(html).toContain('管理面板')
    // 服务端渲染时尚未取到会话，顶栏不能编造“已验证”
    expect(html).toContain('身份待确认')
    expect(html).not.toContain('认证尚未接入')
    expect(html).toContain('锁定面板')
    expect(html).toContain('内容')
  })
})

describe('AdminPanelView (design P19)', () => {
  it('shows the four management entries with their tags', async () => {
    const html = await renderToString(createSSRApp(AdminPanelView))
    for (const title of ['案件记录', '知识库管理', '民警签名管理', '录音查看']) expect(html).toContain(title)
    for (const tag of ['案件查询', '条目增删改', '签名预录入', '双通道录音']) expect(html).toContain(tag)
  })

  it('links the other back-office pages', async () => {
    const html = await renderToString(createSSRApp(AdminPanelView))
    for (const link of ['未完成办理', '模板管理', '操作日志']) expect(html).toContain(link)
    expect(html).not.toContain('民警声纹库')
  })

  it('makes the whole card the click target and no longer calls the back-office a preview', async () => {
    const html = await renderToString(createSSRApp(AdminPanelView))
    expect(html.match(/class="admin-entry-open"/g)).toHaveLength(4)
    // 进入按钮的伪元素铺满卡片：点卡片任意位置都触发同一个按钮
    expect(adminPanelSource).toMatch(/\.admin-entry \{ position: relative;/)
    expect(adminPanelSource).toMatch(/\.admin-entry-open::after \{ content: ''; position: absolute; inset: 0;/)
    expect(html).not.toContain('尚未接入')
    expect(html).not.toContain('界面预览')
  })
})

describe('KnowledgeAdminView entry editor', () => {
  it('edits and creates entries in a modal instead of the narrow side panel', () => {
    expect(knowledgeSource).toContain('<div v-if="editing" class="entry-modal" role="dialog" aria-modal="true"')
    expect(knowledgeSource).toContain('<aside v-if="selected && !editing" class="knowledge-detail"')
    const aside = knowledgeSource.slice(knowledgeSource.indexOf('class="knowledge-detail"'), knowledgeSource.indexOf('</aside>'))
    expect(aside).not.toContain('v-model="form.')
  })
})

describe('LoginView (design P18)', () => {
  it('asks for badge number and password and no longer offers an unauthenticated preview', async () => {
    const html = await renderToString(createSSRApp(LoginView))
    expect(html).toContain('民警身份验证')
    expect(html).toContain('民警警号')
    expect(html).toContain('type="password"')
    expect(html).toContain('验证并进入')
    expect(html).not.toContain('预览 · 未认证')
  })
})
