import { describe, expect, it } from 'vitest'
import type { FormalQuestion } from '../types/templateInterrogation'
import { dynamicAppendAfterId } from './dynamicQuestionInsert'

function question(overrides: Partial<FormalQuestion> & Pick<FormalQuestion, 'id' | 'sortOrder'>): FormalQuestion {
  const { id, sortOrder, ...rest } = overrides
  return {
    id,
    caseId: 'case-a',
    source: 'CASE',
    standardQuestionId: null,
    text: `问题 ${id}`,
    regexPatterns: [],
    aliases: [],
    sectionType: 'BODY',
    templateKey: null,
    templateItemKey: null,
    locked: false,
    formalAnswerText: '',
    firstAskedAt: null,
    sortOrder,
    active: true,
    rounds: [],
    createdAt: null,
    updatedAt: null,
    ...rest,
  }
}

describe('dynamic question append target', () => {
  it('appends after the last dynamic (BODY) question even when closing questions follow it', () => {
    const questions = [
      question({ id: 'opening-1', sortOrder: 10, sectionType: 'OPENING' }),
      question({ id: 'body-1', sortOrder: 20 }),
      question({ id: 'body-2', sortOrder: 30 }),
      question({ id: 'closing-1', sortOrder: 40, sectionType: 'CLOSING' }),
    ]

    expect(dynamicAppendAfterId(questions)).toBe('body-2')
  })

  it('falls back to the last opening question so the first dynamic question lands on top of an empty section', () => {
    const questions = [
      question({ id: 'opening-1', sortOrder: 10, sectionType: 'OPENING' }),
      question({ id: 'opening-2', sortOrder: 20, sectionType: 'OPENING' }),
      question({ id: 'closing-1', sortOrder: 30, sectionType: 'CLOSING' }),
    ]

    expect(dynamicAppendAfterId(questions)).toBe('opening-2')
  })

  it('ignores input order and follows sortOrder', () => {
    const questions = [
      question({ id: 'body-late', sortOrder: 30 }),
      question({ id: 'opening-1', sortOrder: 10, sectionType: 'OPENING' }),
      question({ id: 'body-early', sortOrder: 20 }),
    ]

    expect(dynamicAppendAfterId(questions)).toBe('body-late')
  })

  it('returns null when the record has no questions at all', () => {
    expect(dynamicAppendAfterId([])).toBeNull()
  })
})
