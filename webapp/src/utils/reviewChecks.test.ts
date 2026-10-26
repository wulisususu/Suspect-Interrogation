import { describe, expect, it } from 'vitest'
import type { FactItem, VoiceprintReadiness } from '../types/interrogation'
import { reviewAutoChecks } from './reviewChecks'

const fact = (key: string, status: FactItem['status']) => ({ key, label: key, value: '', status }) as FactItem
const readiness = (patch: Partial<VoiceprintReadiness>) => ({ suspectReady: true, interrogatorReady: true, recorderReady: false, ...patch }) as VoiceprintReadiness

describe('reviewAutoChecks (design P13)', () => {
  it('lists the four automatic checks in design order', () => {
    const checks = reviewAutoChecks([fact('time', 'confirmed')], readiness({}))
    expect(checks.map((item) => item.title)).toEqual(['模板要素', '时间线一致', '同音字纠错', '签署人数与身份'])
  })

  it('passes element coverage only when every core element is confirmed', () => {
    expect(reviewAutoChecks([fact('time', 'confirmed'), fact('place', 'missing')], readiness({}))[0]).toMatchObject({ state: 'pending', detail: '要素 1/2 已覆盖' })
    expect(reviewAutoChecks([fact('time', 'confirmed')], readiness({}))[0]).toMatchObject({ state: 'pass' })
  })

  it('marks checks without a backend as unavailable', () => {
    const checks = reviewAutoChecks([], readiness({}))
    expect(checks[1]!.state).toBe('unavailable')
    expect(checks[2]!.state).toBe('unavailable')
  })

  it('requires the suspect and the interrogating officer before signing', () => {
    expect(reviewAutoChecks([], readiness({}))[3]!.state).toBe('pass')
    expect(reviewAutoChecks([], readiness({ interrogatorReady: false }))[3]!.state).toBe('pending')
  })
})
