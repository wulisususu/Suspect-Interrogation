import { describe, expect, it } from 'vitest'
import { FLOW_STEPS, modeForStep, pageForStep, resolveFlowProgress, stepKeyForMode, type FlowSnapshot } from './steps'

const empty: FlowSnapshot = {
  hasTemplate: false, identityReady: false, hasQuestions: false,
  frozen: false, signed: false, archived: false,
}
const prepared: FlowSnapshot = { ...empty, hasTemplate: true, identityReady: true, hasQuestions: true }

describe('resolveFlowProgress', () => {
  it('declares the five design steps in order', () => {
    expect(FLOW_STEPS.map((step) => step.title)).toEqual(['选模板', '建档', '问答录入', '定稿校验', '签署归档'])
  })

  it('starts a blank case at template selection with only the first two steps open', () => {
    const progress = resolveFlowProgress(empty)
    expect(progress.suggested).toBe('template')
    expect(progress.reachable).toEqual(['template', 'intake'])
    expect(progress.completed).toEqual([])
  })

  it('completes intake from template and identity alone, without any voiceprint', () => {
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

  it('keeps signing open until the case is archived, then marks every step done', () => {
    expect(resolveFlowProgress({ ...prepared, frozen: true, signed: true }).completed).not.toContain('signing')
    const archived = resolveFlowProgress({ ...prepared, frozen: true, signed: true, archived: true })
    expect(archived.completed).toEqual(['template', 'intake', 'dictation', 'review', 'signing'])
    expect(archived.suggested).toBe('signing')
  })
})

describe('pageForStep', () => {
  it('maps ① to the template picker and ② to the single intake page', () => {
    expect(pageForStep('template')).toBe('template')
    expect(pageForStep('intake')).toBe('profile')
  })

  it('shows the record page for steps ③–⑤', () => {
    for (const key of ['dictation', 'review', 'signing'] as const) expect(pageForStep(key)).toBe('interrogation')
  })
})

describe('signing and archive share step ⑤', () => {
  it('shows the export page inside ⑤ once archived', () => {
    expect(modeForStep('signing')).toBe('sign')
    expect(modeForStep('signing', true)).toBe('archive')
    expect(stepKeyForMode('archive')).toBe('signing')
    expect(stepKeyForMode('sign')).toBe('signing')
  })
})
