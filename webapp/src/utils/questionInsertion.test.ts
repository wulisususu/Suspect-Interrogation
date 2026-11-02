import { describe, expect, it } from 'vitest'
import { lastInsertableCardId } from './questionInsertion'

const card = (id: string, sectionType: 'OPENING' | 'BODY' | 'CLOSING') => ({ id, sectionType })

describe('lastInsertableCardId (追加一问的插入点)', () => {
  it('skips the fixed closing cards and anchors on the last body question', () => {
    const cards = [
      card('q1', 'OPENING'),
      card('q2', 'BODY'),
      card('q3', 'CLOSING'),
      card('q4', 'CLOSING'),
    ]
    expect(lastInsertableCardId(cards)).toBe('q2')
  })

  it('falls back to the opening question when the body is empty', () => {
    expect(lastInsertableCardId([card('q1', 'OPENING'), card('q2', 'CLOSING')])).toBe('q1')
  })

  it('returns null when every card is a closing question', () => {
    expect(lastInsertableCardId([card('q1', 'CLOSING'), card('q2', 'CLOSING')])).toBeNull()
  })

  it('returns null for an empty list', () => {
    expect(lastInsertableCardId([])).toBeNull()
  })

  it('anchors on the plain last card when no closing section exists', () => {
    expect(lastInsertableCardId([card('q1', 'BODY'), card('q2', 'BODY')])).toBe('q2')
  })
})
