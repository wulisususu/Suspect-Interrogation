import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import EmptyState from './EmptyState.vue'

const render = (props: Record<string, unknown>, slot?: string) =>
  renderToString(createSSRApp({ render: () => h(EmptyState, props, slot ? { default: () => slot } : undefined) }))

describe('EmptyState', () => {
  it('renders an empty result with its own title and an optional action slot', async () => {
    const html = await render({ kind: 'empty', title: '暂无匹配记录', description: '可清空筛选或调整时间范围' }, '清空筛选条件')
    expect(html).toContain('暂无匹配记录')
    expect(html).toContain('可清空筛选或调整时间范围')
    expect(html).toContain('清空筛选条件')
    expect(html).not.toContain('重试')
  })

  it('labels screens without a backend as 功能待接入 and offers no action', async () => {
    const html = await render({ kind: 'pending', title: '知识库' })
    expect(html).toContain('功能待接入')
    expect(html).not.toContain('<button')
  })

  it('shows a retry button for load failures', async () => {
    const html = await render({ kind: 'error', title: '加载失败', description: '一体机与服务端连接中断' })
    expect(html).toContain('加载失败')
    expect(html).toMatch(/<button[^>]*>重试<\/button>/)
    expect(html).toContain('role="alert"')
  })
})
