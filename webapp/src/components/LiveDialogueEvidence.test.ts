import { describe, expect, it } from 'vitest'
import dialogueSource from './LiveDialoguePanel.vue?raw'
import pageSource from './TemplateDrivenInterrogationPage.vue?raw'
import workspaceSource from '../views/InterrogationWorkspace.vue?raw'
import apiSource from '../api/templateInterrogation.ts?raw'


describe('recognition evidence workbench contract', () => {
  it('renders chronological raw transcript fragments before formal-record grouping', () => {
    expect(dialogueSource).toContain('groupLiveDialogueFragments([...props.dialogue, ...botTurns.value])')
    const transcriptStart = dialogueSource.indexOf('class="dialogue-region transcript-region"')
    const recognitionStart = dialogueSource.indexOf('class="dialogue-region recognition-region"')
    expect(transcriptStart).toBeGreaterThanOrEqual(0)
    expect(recognitionStart).toBeGreaterThan(transcriptStart)
    expect(dialogueSource.slice(transcriptStart, recognitionStart)).toContain('v-for="turn in visibleDialogue"')
    expect(dialogueSource).toContain('speaker-prefix')
    expect(dialogueSource).not.toContain('liveDialogueTurns')
  })

  it('keeps record routing controls out of the transcript and hides recognition evidence', () => {
    const transcriptStart = dialogueSource.indexOf('class="dialogue-region transcript-region"')
    const recognitionStart = dialogueSource.indexOf('class="dialogue-region recognition-region"')
    const transcriptRegion = dialogueSource.slice(transcriptStart, recognitionStart)
    const recognitionRegion = dialogueSource.slice(recognitionStart)

    expect(transcriptRegion).not.toContain('pending-resolution-card')
    expect(transcriptRegion).not.toContain('qa-review-rail')
    expect(recognitionRegion).toContain('pending-resolution-card')
    expect(dialogueSource).not.toContain('查看识别依据')
    expect(dialogueSource).not.toContain('thresholdSource')
    expect(dialogueSource).not.toContain('AI 原判')
  })

  it('allows a human correction without hiding the original AI decision', () => {
    expect(dialogueSource).toContain('人工修正')
    expect(dialogueSource).toContain('correctionReason')
    expect(dialogueSource).toContain("emit('correctFragment'")
    expect(pageSource).toContain('correctFragment')
    expect(workspaceSource).toContain('correctRecognitionFragment')
  })

  it('highlights D-class qa units and exposes both drag modes without replacing raw dialogue', () => {
    expect(dialogueSource).toContain('qaUnits')
    expect(dialogueSource).toContain('待处理')
    expect(dialogueSource).toContain('qa-review-card')
    expect(dialogueSource).toContain('application/x-formal-qa-unit')
    expect(dialogueSource).toContain("mode: 'QA'")
    expect(dialogueSource).toContain("mode: 'ANSWER'")
    expect(dialogueSource).toContain('拖动整组问答')
    expect(dialogueSource).toContain('仅拖动答案')
    expect(dialogueSource).toContain("action: 'IGNORE'")
    expect(dialogueSource).toContain('笔录归档处理')
  })

  it('shows routing status chips for A/B/C while E stays muted and raw-only', () => {
    expect(dialogueSource).toContain('已归档·固定模板')
    expect(dialogueSource).toContain('已归档·已有问题')
    expect(dialogueSource).toContain('已新增·现场问题')
    expect(dialogueSource).toContain('已忽略·仅原始对话')
    expect(dialogueSource).toContain('qa-status-muted')
  })

  it('wires qa review resolution through the page and workspace stores', () => {
    expect(pageSource).toContain('resolveQaUnit')
    expect(pageSource).toContain('workspace.qaUnits')
    expect(workspaceSource).toContain('resolveQaUnit')
  })

  it('exposes rollback for applied qa matches and keeps rolled-back matches one-way', () => {
    expect(dialogueSource).toContain('回退本次匹配')
    expect(dialogueSource).toContain("unit.status === 'APPLIED'")
    expect(dialogueSource).toContain("unit.status === 'ROLLED_BACK'")
    expect(workspaceSource).toContain('rollbackQaUnit')
    expect(apiSource).toContain('/rollback')
  })

  it('makes persisted raw dialogue turns draggable into formal answers', () => {
    expect(dialogueSource).toContain('startDialogueDrag')
    expect(dialogueSource).toContain(':draggable="turn.fragments.some((item) => !isBotFragment(item))"')
    expect(dialogueSource).toContain('@dragstart="startDialogueDrag($event, turn.fragments)"')
    expect(dialogueSource).toContain("const FORMAL_ANSWER_FRAGMENT_MIME = 'application/x-formal-answer-fragments'")
    expect(pageSource).toContain('attachFragmentAnswer')
    expect(workspaceSource).toContain('attachFormalFragmentAnswer')
    expect(apiSource).toContain('/answer-fragments')
  })
})
