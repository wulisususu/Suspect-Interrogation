import { describe, expect, it } from 'vitest'
import type { CaseSummary } from '../types/interrogation'
import { unfinishedCases } from './kioskLobby'

const c = (id: string, workflowState: string, state = 'DRAFT') => ({ id, workflowState, state }) as CaseSummary

describe('unfinishedCases', () => {
  it('keeps every case that has started but not been archived', () => {
    const cases = [
      c('a', 'IDENTITY_READY'), c('b', 'QUESTIONING', 'INTERROGATING'), c('c', 'FROZEN', 'SIGNING'),
      c('d', 'REPORT_GENERATED', 'COMPLETED'), c('e', 'SIGNED', 'ARCHIVED'), c('f', 'INIT'),
    ]
    expect(unfinishedCases(cases).map((item) => item.id)).toEqual(['a', 'b', 'c'])
  })

  it('treats a case without a workflow state as a draft', () => {
    expect(unfinishedCases([{ id: 'x', state: 'DRAFT' } as CaseSummary])).toEqual([])
  })
})
