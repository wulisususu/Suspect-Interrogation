import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import TemplatePickerPage from './TemplatePickerPage.vue'

const facts = [
  { key: 'time', label: '时间', value: '', status: 'pending' },
  { key: 'place', label: '地点', value: '', status: 'pending' },
  { key: 'contact', label: '联系方式', value: '', status: 'missing' },
]
const questions = ['你因何事来公安机关？', '你的基本情况？', '你还有什么要补充的？', '你以上说的是否属实？']
  .map((text, index) => ({ id: `q${index}`, text, sortOrder: index, active: true, sectionType: 'OPENING' }))
const render = (props: Record<string, unknown>) => renderToString(createSSRApp(TemplatePickerPage, { templateKey: 'SUSPECT_INQUIRY_V1', facts, questions, ...props }))

describe('TemplatePickerPage (design P05)', () => {
  it('shows the case template as the selected card', async () => {
    const html = await render({})
    expect(html).toContain('选择笔录模板')
    expect(html).toContain('嫌疑人询问')
    expect(html).toContain('已选此模板')
    expect(html).toContain('全部 (1)')
    expect(html).toContain('确认模板 · 进入建档')
  })

  it('previews core elements and the first three preset questions', async () => {
    const html = await render({})
    expect(html).toContain('核心要素（2 项）')
    expect(html).toContain('时间')
    expect(html).not.toContain('联系方式')
    expect(html).toContain('你因何事来公安机关？')
    expect(html).toContain('你还有什么要补充的？')
    expect(html).not.toContain('你以上说的是否属实？')
    expect(html).toContain('共 4 条')
  })

  it('keeps unbuilt template actions visibly disabled', async () => {
    const html = await render({})
    for (const label of ['新建模板', '跳过模板 · 空白笔录']) {
      expect(html).toMatch(new RegExp(`<button[^>]*disabled[^>]*title="功能待接入"[^>]*>(?:(?!</button>)[\\s\\S])*${label}`))
    }
  })

  it('shows an empty state when the case has no template yet', async () => {
    const html = await render({ templateKey: null, questions: [] })
    expect(html).toContain('暂无可用模板')
    expect(html).not.toContain('已选此模板')
  })
})
