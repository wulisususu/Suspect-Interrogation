import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import DraftQuestionRail from './DraftQuestionRail.vue'

const questions = [
  { id: 'q1', text: '请讲一下事情的经过？', sortOrder: 1, active: true, formalAnswerText: '已经写入正本的回答', rounds: [] },
  { id: 'q2', text: '当时有谁在场？', sortOrder: 2, active: true, formalAnswerText: '', rounds: [{ id: 'r2', status: 'CLOSED', answerText: '录到但还没摘入' }] },
  { id: 'q3', text: '你最后一次见到他是什么时候？', sortOrder: 3, active: true, formalAnswerText: '', rounds: [] },
]
const render = (props: Record<string, unknown> = {}) => renderToString(createSSRApp(DraftQuestionRail, {
  questions, sessionStatus: 'RUNNING', recordingQuestionId: null, captureAvailable: true, ...props,
}))
const card = (html: string, text: string) => html.slice(html.indexOf(text), html.indexOf('</article>', html.indexOf(text)))

describe('DraftQuestionRail cards (design P07, states A/B)', () => {
  it('marks a recorded answer 已入正本 and offers 重录 / 在正本中查看', async () => {
    const html = card(await render(), '请讲一下事情的经过？')
    expect(html).toContain('已入正本')
    expect(html).toContain('重录这题')
    expect(html).toContain('在正本中查看')
    expect(html).not.toContain('摘入正本')
  })

  it('keeps a transcribed answer 待摘入 until the officer writes it into the record', async () => {
    const html = card(await render(), '当时有谁在场？')
    expect(html).toContain('待摘入')
    expect(html).toContain('录到但还没摘入')
    expect(html).toContain('摘入正本')
  })

  it('invites a spoken answer on questions not yet asked', async () => {
    const html = card(await render(), '你最后一次见到他是什么时候？')
    expect(html).toContain('未开始')
    expect(html).toContain('点击此处回答')
    expect(html).not.toContain('重录这题')
  })

  it('shows the timer, live text and 结束并转写 on the card being recorded', async () => {
    const html = await render({ recordingQuestionId: 'q3', captureElapsedMs: 12_000, liveText: '锁了，我平时上下班都锁的' })
    const recording = card(html, '你最后一次见到他是什么时候？')
    expect(recording).toContain('● 录音中')
    expect(recording).toContain('录音中 00:12')
    expect(recording).toContain('锁了，我平时上下班都锁的')
    expect(recording).toContain('结束并转写')
    expect(html).toContain('1 卡录制中')
    // 录音进行中，其他卡的录音入口一律禁用
    for (const button of html.match(/<button[^>]*class="draft-action is-(?:answer|secondary)"[^>]*>/g) ?? []) expect(button).toContain('disabled')
  })

  it('lets the officer start the interrogation by answering the first card', async () => {
    const html = await render({ sessionStatus: 'READY' })
    expect(html).toContain('点任一题卡的「点击此处回答」即开始询问')
    const answer = html.match(/<button[^>]*class="draft-action is-answer"[^>]*>/)?.[0] ?? ''
    expect(answer).not.toContain('disabled')
  })

  it('disables recording once the record is locked or the session paused', async () => {
    for (const props of [{ locked: true }, { sessionStatus: 'PAUSED' }]) {
      const html = await render(props)
      for (const button of html.match(/<button[^>]*class="draft-action is-(?:answer|secondary)"[^>]*>/g) ?? []) expect(button).toContain('disabled')
    }
    expect(await render({ sessionStatus: 'PAUSED' })).toContain('继续询问')
  })

  it('appends a question by holding to speak, with a typed fallback', async () => {
    const html = await render()
    expect(html).toContain('追加一问 · 按住说话，说完自动成卡')
    expect(html).toContain('手动输入')
  })
})
