import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ReviewChecklistPanel from './ReviewChecklistPanel.vue'
import ReviewRecordPreview from './ReviewRecordPreview.vue'

const facts = [
  { key: 'time', label: '时间', value: '7 时 20 分', status: 'confirmed' },
  { key: 'place', label: '地点', value: '', status: 'pending' },
  { key: 'motive', label: '动机 / 目的', value: '', status: 'missing' },
]
const questions = [
  { id: 'q1', text: '什么时候发现车不见的？', sortOrder: 1, active: true, formalAnswerText: '今天早上 7 时 20 分。', rounds: [] },
  { id: 'q2', text: '车是什么牌子？', sortOrder: 2, active: true, formalAnswerText: '', rounds: [{ id: 'r2', status: 'CLOSED', answerText: '雅迪' }] },
  { id: 'q3', text: '有没有看到可疑人员？', sortOrder: 3, active: true, formalAnswerText: '', rounds: [] },
]
const autoChecks = [
  { key: 'elements', title: '模板要素', state: 'pending', detail: '要素 1/3 已覆盖' },
  { key: 'timeline', title: '时间线一致', state: 'unavailable', detail: '' },
  { key: 'homophone', title: '同音字纠错', state: 'unavailable', detail: '' },
  { key: 'signers', title: '签署人数与身份', state: 'pass', detail: '被询问人 王某某 · 询问人 张伟 · 记录人 刘敏' },
]
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(ReviewChecklistPanel, {
  summary: { id: 'C-1', suspectName: '王某某', idNumber: '330501199205142319' }, facts, questions, templateTitle: '盗窃（电动车）',
  blockReason: '', frozen: false, unresolvedFragments: 0, unresolvedQa: 0, autoChecks, ...props,
}))

describe('ReviewChecklistPanel (design P13 / state C)', () => {
  it('counts core elements as 已确认 / 待补 / 未获取 including the ID number', async () => {
    const html = await render()
    expect(html).toContain('已确认 2 · 待补 1 · 未获取 1')
    expect(html).toContain('当事人身份证号')
    expect(html).toContain('已确认 ✓')
    expect(html).toContain('未获取项将以「未获取」如实记入笔录')
  })

  it('lists pre-finalise checks as hints only, with no manual acknowledgement boxes', async () => {
    const html = await render()
    expect(html).toContain('定稿前检查')
    expect(html).toContain('笔录格式与《盗窃（电动车）》模板一致')
    expect(html).toContain('签署人数与身份 · 被询问人 王某某')
    expect(html).toContain('时间线一致（待接入）')
    expect(html).toContain('1 条录音回答尚未摘入正本')
    expect(html).not.toContain('type="checkbox"')
  })

  it('surfaces only the blockers the backend would reject', async () => {
    const html = await render({ unresolvedFragments: 3, blockReason: '还有 3 条转写片段待确认或丢弃' })
    expect(html).toContain('3 条转写片段未处理')
    expect(html).toContain('还有 3 条转写片段待确认或丢弃')
  })
})

describe('ReviewRecordPreview (design P13 right column)', () => {
  it('previews every question and marks unanswered ones 未获取', async () => {
    const html = await renderToString(createSSRApp(ReviewRecordPreview, { questions }))
    expect(html).toContain('1 问已答 · 2 题未获取')
    expect(html).toContain('答：今天早上 7 时 20 分。')
    expect(html).toContain('答：（未获取）')
    expect(html).toContain('已录音但未摘入正本')
  })
})
