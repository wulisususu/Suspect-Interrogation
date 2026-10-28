import { describe, expect, it } from 'vitest'

import pageSource from './TemplateDrivenInterrogationPage.vue?raw'
import workspaceSource from '../views/InterrogationWorkspace.vue?raw'
import formalSource from './FormalTemplatePanel.vue?raw'
import dialogueSource from './LiveDialoguePanel.vue?raw'
import preparationSource from './QuestionPreparationPanel.vue?raw'

const componentModules = import.meta.glob('./*.vue')

describe('template-driven interrogation C-page contract', () => {
  it('renders the formal transcript and live dialogue as explicit sibling panels', () => {
    expect(pageSource).toContain('template-interrogation-grid')
    expect(pageSource).toContain('FormalTemplatePanel')
    expect(pageSource).toContain('LiveDialoguePanel')
  })

  it('keeps the formal transcript header out of the C-page content area', () => {
    expect(formalSource).not.toContain('class="formal-header"')
    expect(formalSource).not.toContain('<h2>嫌疑人讯问笔录</h2>')
    expect(formalSource).not.toContain('<span class="panel-kicker">正式笔录</span>')
  })

  it('keeps formal-record header data editable and grows multi-line QA editors', () => {
    expect(formalSource).toContain('record-meta-editor')
    expect(formalSource).toContain('@input="autoGrow($event)"')
    expect(formalSource).toContain("emit('updateHeader'")
  })

  it('keeps legacy conflict and low-confidence business marks out of the new formal page', () => {
    expect(formalSource).not.toContain('矛盾标记')
    expect(formalSource).not.toContain('标记矛盾')
    expect(formalSource).not.toContain('低置信度')
  })

  it('keeps raw dialogue actions separate from the formal transcript', () => {
    expect(dialogueSource).toContain('加入本案笔录')
    expect(dialogueSource).toContain('忽略')
    expect(dialogueSource).toContain('追加到原回答')
    expect(dialogueSource).toContain('新增一轮问答')
    expect(dialogueSource).toContain('↓ 最新消息')
  })

  it('provides pre-interrogation library, manual and voice-assisted preparation', () => {
    expect(preparationSource).toContain('问题库')
    expect(preparationSource).toContain('手动输入')
    expect(preparationSource).toContain('语音输入')
    expect(preparationSource).toContain('加入本案问题')
  })

  it('wires preparation voice dictation to a real runtime instead of a disabled placeholder', () => {
    expect(pageSource).not.toContain(':voice-available="false"')
    expect(pageSource).toContain(':voice-draft="questionDictationDraft"')
    expect(pageSource).toContain('@voice-start="emit(\'questionDictationStart\')"')
    expect(pageSource).toContain('@voice-stop="emit(\'questionDictationStop\')"')
  })

  it('shows live dialogue without any voiceprint gate now that voiceprints left the workflow', () => {
    expect(pageSource).not.toContain('VoiceprintEnrollmentGate')
    expect(workspaceSource).not.toContain('VoiceprintSetupPage')
    expect(workspaceSource).not.toContain('autoVoiceprint')
    expect(pageSource).toContain('<LiveDialoguePanel')
    expect(pageSource).not.toContain('readiness.suspectReady')
    expect(pageSource).not.toContain('dialogue-voiceprint-hint')
  })

  it('retires the legacy monolithic interrogation C-page', () => {
    expect(Object.keys(componentModules)).not.toContain('./InterrogationPage.vue')
  })
})
