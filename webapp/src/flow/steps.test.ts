import { describe, expect, it } from 'vitest'
import { FLOW_STEPS, resolveFlowProgress, type FlowSnapshot } from './steps'

const empty: FlowSnapshot = {
  hasTemplate: false, identityReady: false, voiceprintReady: false, hasQuestions: false,
  frozen: false, signed: false, archived: false,
}
const prepared: FlowSnapshot = { ...empty, hasTemplate: true, identityReady: true, voiceprintReady: true, hasQuestions: true }

describe('resolveFlowProgress', () => {
  it('declares the six design steps in order', () => {
    expect(FLOW_STEPS.map((step) => step.title)).toEqual(['选模板', '建档', '问答录入', '定稿校验', '签署归档', '归档导出'])
  })

  it('starts a blank case at template selection with only the first two steps open', () => {
    const progress = resolveFlowProgress(empty)
    expect(progress.suggested).toBe('template')
    expect(progress.reachable).toEqual(['template', 'intake'])
    expect(progress.completed).toEqual([])
  })

  it('opens dictation and review once intake is complete and questions exist', () => {
    const progress = resolveFlowProgress(prepared)
    expect(progress.completed).toEqual(['template', 'intake'])
    expect(progress.reachable).toEqual(['template', 'intake', 'dictation', 'review'])
    expect(progress.suggested).toBe('dictation')
  })

  it('opens signing after the record is frozen', () => {
    const progress = resolveFlowProgress({ ...prepared, frozen: true })
    expect(progress.reachable).toContain('signing')
    expect(progress.completed).toEqual(['template', 'intake', 'dictation', 'review'])
    expect(progress.suggested).toBe('signing')
  })

  it('opens the archive step once signed', () => {
    expect(resolveFlowProgress({ ...prepared, frozen: true, signed: true }).reachable).toContain('archive')
  })

  it('lands on the archive step when the case is archived', () => {
    expect(resolveFlowProgress({ ...prepared, frozen: true, signed: true, archived: true }).suggested).toBe('archive')
  })
})
