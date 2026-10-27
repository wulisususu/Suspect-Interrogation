import { beforeEach, describe, expect, it } from 'vitest'
import { currentOperatorId, resetCurrentOperator, setCurrentOperator } from './operator'

describe('operator identity', () => {
  beforeEach(() => resetCurrentOperator())

  it('has no operator until a real officer is selected', () => {
    expect(currentOperatorId()).toBeUndefined()
  })

  it('never fabricates a placeholder operator', () => {
    setCurrentOperator('   ')
    expect(currentOperatorId()).toBeUndefined()
    setCurrentOperator(null)
    expect(currentOperatorId()).toBeUndefined()
  })

  it('returns the selected officer id for audit binding', () => {
    setCurrentOperator('OFFICER-42')
    expect(currentOperatorId()).toBe('OFFICER-42')
  })

  it('clears the operator when leaving a case', () => {
    setCurrentOperator('OFFICER-42')
    resetCurrentOperator()
    expect(currentOperatorId()).toBeUndefined()
  })
})
