import { describe, expect, it } from 'vitest'
import type { FactItem } from '../types/interrogation'
import { reviewAutoChecks } from './reviewChecks'

const fact = (key: string, status: FactItem['status']) => ({ key, label: key, value: '', status }) as FactItem
const summary = { suspectName: '王某某', officerName: '张伟' }

describe('reviewAutoChecks (design P13)', () => {
  it('lists the four automatic checks in design order', () => {
    const checks = reviewAutoChecks([fact('time', 'confirmed')], summary, '刘敏')
    expect(checks.map((item) => item.title)).toEqual(['模板要素', '时间线一致', '同音字纠错', '签署人数与身份'])
  })

  it('passes element coverage only when every core element is confirmed', () => {
    expect(reviewAutoChecks([fact('time', 'confirmed'), fact('place', 'missing')], summary, '刘敏')[0]).toMatchObject({ state: 'pending', detail: '要素 1/2 已覆盖' })
    expect(reviewAutoChecks([fact('time', 'confirmed')], summary, '刘敏')[0]).toMatchObject({ state: 'pass' })
  })

  it('marks checks without a backend as unavailable', () => {
    const checks = reviewAutoChecks([], summary, '刘敏')
    expect(checks[1]!.state).toBe('unavailable')
    expect(checks[2]!.state).toBe('unavailable')
  })

  it('takes signers from the intake record instead of voiceprint bindings', () => {
    expect(reviewAutoChecks([], summary, '刘敏')[3]).toMatchObject({ state: 'pass', detail: '被询问人 王某某 · 询问人 张伟 · 记录人 刘敏' })
  })

  it('stays pending while a signer is missing and ignores placeholder names', () => {
    const check = reviewAutoChecks([], { suspectName: '待录入', officerName: '当前警官' }, '')[3]!
    expect(check.state).toBe('pending')
    expect(check.detail).toBe('被询问人 未填写 · 询问人 未填写 · 记录人 未填写')
  })
})
