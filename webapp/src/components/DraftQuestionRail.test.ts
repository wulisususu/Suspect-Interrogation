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

  it('streams the live transcript while holding to append a question (parity with card recording)', async () => {
    const html = await render({ questionRecording: true, liveText: '你当时第一次实施盗窃是什么时候', captureElapsedMs: 3000 })
    expect(html).toContain('正在听问题 00:03 · 松开即成卡')
    expect(html).toContain('你当时第一次实施盗窃是什么时候')
    const source = (await import('./DraftQuestionRail.vue?raw')).default
    expect(source).toContain('class="draft-add-live"')
    expect(source).toContain('<RecorderWaveformCanvas v-if="audioLevels?.length" class="draft-add-wave"')
  })

  it('never anchors the appended question on a fixed closing card (AAC708 regression)', async () => {
    // 嫌疑人询问模板的最后一张卡是固定结尾（签字捺印），旧逻辑拿它当插入点，
    // 后端必然拒绝：动态问题不能插入固定结尾之后。现在插入点由
    // lastInsertableCardId 选取，经 utils/questionInsertion.test.ts 单测守护。
    const source = (await import('./DraftQuestionRail.vue?raw')).default
    expect(source).toContain('lastInsertableCardId(cards.value)')
    expect(source).toContain("question.sectionType ?? 'BODY'")
  })

  it('explains why the hold-to-talk entry is unavailable instead of failing silently', async () => {
    // 冻结 / 会话结束 / 暂停时按钮置灰或降级输入框，原因必须在页面上可见。
    expect(await render({ locked: true })).toContain('笔录已冻结')
    expect(await render({ sessionStatus: 'COMPLETED' })).toContain('本次询问已结束')
    expect(await render({ sessionStatus: 'PAUSED' })).toContain('询问已暂停，继续询问后可录音')
    expect(await render({ captureAvailable: false })).toContain('录音设备未就绪')
    const source = (await import('./DraftQuestionRail.vue?raw')).default
    expect(source).toContain('class="draft-add-blocked"')
    expect(source).toContain(':title="answerBlockedReason || undefined"')
  })

  it('offers undo / clear-and-rerecord / done while an answer is being edited (design P06)', async () => {
    const source = (await import('./DraftQuestionRail.vue?raw')).default
    expect(source).toContain('编辑中 · 光标在句末')
    expect(source).toContain('撤销')
    expect(source).toContain('清空重说')
    expect(source).toContain('完成 · 收起键盘')
    expect(source).toContain('@focus="startEdit(card.id)"')
  })
})

describe('DraftQuestionRail question edit / remove', () => {
  const extra = [
    ...questions,
    { id: 'q7', text: '你当时第一次实施盗窃是什么时候', source: 'LIVE', sectionType: 'BODY', locked: false, sortOrder: 7, active: true, formalAnswerText: '', rounds: [] },
    { id: 'qf', text: '以上笔录你仔细阅看，若无误则签字捺印？', sectionType: 'CLOSING', locked: true, sortOrder: 9, active: true, formalAnswerText: '', rounds: [] },
    { id: 'qc', text: '你还有什么要补充的？', sectionType: 'CLOSING', locked: false, sortOrder: 8, active: true, formalAnswerText: '', rounds: [] },
  ]

  it('offers 修改问题 and 删除此题 on every body card, including voice-appended LIVE ones', async () => {
    const html = await render({ questions: extra })
    for (const [ordinal, text] of [[1, '请讲一下事情的经过？'], [4, '你当时第一次实施盗窃是什么时候']] as const) {
      const one = card(html, text)
      expect(one).toContain(`aria-label="修改第 ${ordinal} 题问题"`)
      expect(one).toContain(`aria-label="删除第 ${ordinal} 题"`)
    }
  })

  it('follows the backend: fixed (locked) questions get neither, closing questions cannot be removed', async () => {
    const html = await render({ questions: extra })
    const fixed = card(html, '以上笔录你仔细阅看')
    expect(fixed).not.toContain('修改第')
    expect(fixed).not.toContain('删除第')
    const closing = card(html, '你还有什么要补充的？')
    expect(closing).toContain('修改第')
    expect(closing).not.toContain('删除第')
  })

  it('disables question tools while recording or locked, and hides them on the card being recorded', async () => {
    const recording = await render({ questions: extra, recordingQuestionId: 'q3' })
    expect(card(recording, '你最后一次见到他是什么时候？')).not.toContain('修改第')
    for (const button of card(recording, '请讲一下事情的经过？').match(/<button[^>]*class="draft-tool[^"]*"[^>]*>/g) ?? []) expect(button).toContain('disabled')
    for (const button of (await render({ questions: extra, locked: true })).match(/<button[^>]*class="draft-tool[^"]*"[^>]*>/g) ?? []) expect(button).toContain('disabled')
  })

  it('removes only after a second, explicit confirmation', async () => {
    const source = (await import('./DraftQuestionRail.vue?raw')).default
    expect(source).toContain("if (removeConfirmId.value !== cardId) { removeConfirmId.value = cardId; return }")
    expect(source).toContain('确认删除')
  })
})
