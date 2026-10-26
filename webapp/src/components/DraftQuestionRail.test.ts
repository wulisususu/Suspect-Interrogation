import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import DraftQuestionRail from './DraftQuestionRail.vue'

const questions = [
  { id: 'q1', text: '请讲一下事情的经过？', sortOrder: 1, active: true, formalAnswerText: '已经写入正本的回答', rounds: [] },
  { id: 'q2', text: '当时有谁在场？', sortOrder: 2, active: true, formalAnswerText: '', rounds: [{ answerText: '录到但还没插入' }] },
  { id: 'q3', text: '你最后一次见到他是什么时候？', sortOrder: 3, active: true, formalAnswerText: '', rounds: [] },
]
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(DraftQuestionRail, {
  questions, qaUnits: [], pendingQuestions: [], captureRunning: false, captureAvailable: true, ...props,
}))
const card = (html: string, text: string) => html.slice(html.indexOf(text), html.indexOf('</article>', html.indexOf(text)))

describe('DraftQuestionRail cards (design P08–P10)', () => {
  it('offers 在正本中查看 for recorded answers', async () => {
    const html = card(await render(), '请讲一下事情的经过？')
    expect(html).toContain('重录这题')
    expect(html).toContain('在正本中查看')
    expect(html).not.toContain('插入正本')
  })

  it('offers 插入正本 for answers captured but not yet in the record', async () => {
    const html = card(await render(), '当时有谁在场？')
    expect(html).toContain('重录这题')
    expect(html).toContain('插入正本')
  })

  it('invites a spoken answer on questions not yet asked', async () => {
    const html = card(await render(), '你最后一次见到他是什么时候？')
    expect(html).toContain('点击此处回答')
    expect(html).not.toContain('重录这题')
  })

  it('disables every card action once the record is locked', async () => {
    const html = await render({ locked: true })
    const actions = html.match(/<button[^>]*class="draft-action[^"]*"[^>]*>/g) ?? []
    expect(actions.length).toBeGreaterThan(0)
    for (const button of actions) expect(button).toContain('disabled')
  })
})
