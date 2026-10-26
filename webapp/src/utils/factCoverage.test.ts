import { describe, expect, it } from 'vitest'
import type { FactItem } from '../types/interrogation'
import { coreFacts } from './factCoverage'

const fact = (key: string, status: FactItem['status'] = 'pending') => ({ key, label: key, value: '', status }) as FactItem

describe('coreFacts', () => {
  it('keeps the case elements in template order and drops record-header facts', () => {
    const facts = [fact('contact'), fact('process'), fact('time'), fact('interrogation_place'), fact('after'), fact('place')]
    expect(coreFacts(facts).map((item) => item.key)).toEqual(['time', 'place', 'process', 'after'])
  })
})
