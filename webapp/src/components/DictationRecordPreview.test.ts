import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import DictationRecordPreview from './DictationRecordPreview.vue'

const summary = { id: 'C-1', suspectName: '王某某', officerName: '张伟', gender: '女', birthDate: '1992-05-14', idNumber: '330501199205142319', createdAt: Date.UTC(2026, 9, 20, 2, 30) }
const facts = [
  { key: 'officer_unit', label: '询问人工作单位', value: '湖州市公安局吴兴分局', status: 'confirmed' },
  { key: 'recorder_name', label: '记录人', value: '刘敏', status: 'confirmed' },
  { key: 'interrogation_place', label: '询问地点', value: '一楼报案大厅', status: 'confirmed' },
  { key: 'contact', label: '联系方式', value: '未录入', status: 'missing' },
]
const questions = [
  { id: 'q1', text: '请讲一下事情的经过？', sortOrder: 1, active: true, formalAnswerText: '车停在楼下被偷了。', rounds: [] },
  { id: 'q2', text: '车辆当时锁了吗？', sortOrder: 2, active: true, formalAnswerText: '', rounds: [{ id: 'r2', status: 'CLOSED', answerText: '锁了，锁在柱子上。' }] },
  { id: 'q3', text: '有没有看到可疑人员？', sortOrder: 3, active: true, formalAnswerText: '', rounds: [] },
]
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(DictationRecordPreview, {
  summary, facts, session: { startedAt: null, endedAt: null }, questions, ...props,
}))

describe('DictationRecordPreview (design P07 right column)', () => {
  it('heads the record with the unit name and compact read-only identity lines', async () => {
    const html = await render()
    expect(html).toContain('湖州市公安局吴兴分局')
    expect(html).toContain('询问笔录')
    expect(html).toMatch(/询问人：<em[^>]*>张伟（工作单位：湖州市公安局吴兴分局）<\/em>/)
    expect(html).toContain('3305**********2319')
    expect(html).toContain('1992 年 5 月 14 日')
    expect(html).toMatch(/联系方式：<em class="is-empty"[^>]*>未填写<\/em>/)
    expect(html).not.toContain('<input')
    expect(html).not.toContain('<textarea')
  })

  it('lists recorded answers, previews drafts with 摘入正本 and summarises unanswered questions', async () => {
    const html = await render()
    expect(html).toContain('Q1 · ')
    expect(html).toContain('已入正本')
    expect(html).toContain('车停在楼下被偷了。')
    expect(html).toContain('Q2 · 待摘入（以下为录音转写草稿）')
    expect(html).toContain('锁了，锁在柱子上。')
    expect(html).toContain('摘入正本')
    expect(html).not.toContain('有没有看到可疑人员？')
    expect(html).toContain('另有 1 题未作答')
  })
})

describe('DictationRecordPreview grouped by template element', () => {
  it('groups answers under their core element once questions carry an element key', async () => {
    const coreFactsList = [
      { key: 'time', label: '时间', value: '', status: 'confirmed' },
      { key: 'place', label: '地点', value: '', status: 'pending' },
    ]
    const keyed = [
      { ...questions[0], elementKey: 'time' },
      { ...questions[1], elementKey: 'place' },
      { ...questions[2], formalAnswerText: '没有看到。' },
    ]
    const html = await render({ facts: [...facts, ...coreFactsList], questions: keyed })
    expect(html).toContain('① 时间')
    expect(html).toContain('② 地点')
    expect(html).toContain('待补（模板要素 · 以下待摘入）')
    expect(html).toContain('其他问答')
    expect(html).not.toContain('Q1 · ')
  })
})
