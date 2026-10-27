import { describe, expect, it } from 'vitest'
import type { FactItem } from '../types/interrogation'
import { coreFacts, factCoverage } from './factCoverage'

const fact = (key: string, status: FactItem['status'] = 'pending') => ({ key, label: key, value: '', status }) as FactItem

describe('coreFacts', () => {
  it('keeps the case elements in template order and drops record-header facts', () => {
    const facts = [fact('contact'), fact('process'), fact('time'), fact('interrogation_place'), fact('after'), fact('place')]
    expect(coreFacts(facts).map((item) => item.key)).toEqual(['time', 'place', 'process', 'after'])
  })
})

describe('factCoverage', () => {
  it('counts confirmed core elements and lists the rest as missing', () => {
    const facts = [fact('time', 'confirmed'), fact('place', 'confirmed'), fact('motive', 'confirmed'), fact('method', 'confirmed'), fact('process', 'pending'), fact('after', 'missing'), fact('contact', 'missing')]
    const coverage = factCoverage(facts)
    expect(coverage.total).toBe(6)
    expect(coverage.covered).toBe(4)
    expect(coverage.missing.map((item) => item.key)).toEqual(['process', 'after'])
  })
})
