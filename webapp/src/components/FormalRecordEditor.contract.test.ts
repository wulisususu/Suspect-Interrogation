import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(__dirname)
const formal = fs.readFileSync(path.join(root, 'FormalTemplatePanel.vue'), 'utf8')
const live = fs.readFileSync(path.join(root, 'LiveDialoguePanel.vue'), 'utf8')
const interrogationStore = fs.readFileSync(path.join(root, '../stores/interrogation.ts'), 'utf8')
const templateStore = fs.readFileSync(path.join(root, '../stores/templateInterrogation.ts'), 'utf8')
const workspace = fs.readFileSync(path.join(root, '../views/InterrogationWorkspace.vue'), 'utf8')

describe('formal record editor source contract', () => {
  it('renders paper-style fixed/body/closing sections without in-paper action buttons (design P07)', () => {
    expect(formal).toContain('正式询问笔录编辑器')
    expect(formal).toContain('openingQuestions')
    expect(formal).toContain('bodyQuestions')
    expect(formal).toContain('closingQuestions')
    // 签名、冻结、打印分别在 ④ 定稿校验与 ⑤ 签署归档完成，③ 的正本只做实时预览。
    expect(formal).not.toContain('record-top-actions')
    expect(formal).not.toContain('结束并冻结笔录')
  })


  it('keeps printing wired through the workspace', () => {
    expect(workspace).toContain('window.print()')
    expect(workspace).toContain('@print="printFormalRecord"')
  })

  it('keeps legacy pending drag compatibility and adds the qa-unit drag MIME', () => {
    expect(live).toContain('application/x-formal-pending-question')
    expect(formal).toContain('application/x-formal-pending-question')
    const qaMime = 'application/x-formal-qa-unit'
    expect(live).toContain(qaMime)
    expect(formal).toContain(qaMime)
    expect(formal).toContain("emit('resolveQaUnit'")
  })

  it('accepts whole QA on BODY gaps/questions and answer-only on answer areas', () => {
    expect(formal).toContain('dropQaCreateLive')
    expect(formal).toContain("action: 'CREATE_LIVE'")
    expect(formal).toContain('dropQaOnQuestion')
    expect(formal).toContain("action: 'LINK_QA'")
    expect(formal).toContain('dropAnswerOnQuestion')
    expect(formal).toContain("action: 'LINK_ANSWER'")
  })

  it('accepts raw dialogue fragments on every formal answer area', () => {
    expect(live).toContain('application/x-formal-answer-fragments')
    expect(formal).toContain('application/x-formal-answer-fragments')
    expect(formal).toContain("emit('attachFragmentAnswer'")
    expect(formal).toContain('聊天记录或答案可拖到这里')
  })

  it('accepts officer dialogue fragments on dynamic question gaps', () => {
    expect(formal).toContain('dropLiveQuestionFromFragments')
    expect(formal).toContain("emit('createLiveQuestionFromFragments'")
    expect(templateStore).toContain('createLiveQuestionFromFragments')
    expect(workspace).toContain('@create-live-question-from-fragments=')
  })

  it('renders the canonical case-question answer while retaining round provenance', () => {
    expect(formal).toContain('formalAnswerText')
    expect(formal).toContain('canonicalAnswerDrafts')
    expect(formal).toContain("emit('updateAnswer', question.id, answer)")
    expect(formal).toContain('latestRound(q.id)?.actualQuestionText')
    expect(formal).not.toContain('answerDrafts[latestRound(q.id)!.id]')
    expect(formal).not.toContain('manualAnswerDrafts')
  })

  it('uses committed routing events as the formal-workspace correctness signal', () => {
    expect(interrogationStore).toContain('formalRecordRevision')
    expect(interrogationStore).toContain("event.event === 'QA_UNIT_UPDATED'")
    expect(interrogationStore).toContain("event.event === 'FORMAL_RECORD_UPDATED'")
    expect(interrogationStore).toContain('formalRecordRevision.value += 1')
    expect(templateStore).toContain('interrogation.formalRecordRevision')
    expect(templateStore).toContain('watch(')
  })

  // legacy routing emits ASR_FRAGMENT but no committed Qwen routing revision event.
  it('retains raw-fragment workspace refresh as legacy-mode compatibility only', () => {
    const start = templateStore.indexOf('function handleAsrFragment')
    const end = templateStore.indexOf('function attachCaptureBridge', start)
    expect(start).toBeGreaterThanOrEqual(0)
    expect(end).toBeGreaterThan(start)
    const handler = templateStore.slice(start, end)
    expect(handler).toContain('upsertDialogue(fragment, scope)')
    expect(handler).toContain('scheduleWorkspaceRefresh(scope)')
    expect(handler.indexOf('scheduleWorkspaceRefresh(scope)')).toBeGreaterThan(handler.indexOf('upsertDialogue(fragment, scope)'))
  })
})
