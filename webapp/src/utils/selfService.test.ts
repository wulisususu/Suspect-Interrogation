import { describe, expect, it } from 'vitest'
import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import {
  SELF_SERVICE_STEPS, answerStats, birthText, circled, firstUnansweredIndex, maskIdNumber, maskPhone,
  nextUnansweredIndex, selfServiceQuestions,
} from './selfService'

function question(id: string, sortOrder: number, extra: Partial<FormalQuestion> = {}): FormalQuestion {
  return {
    id, caseId: 'c1', source: 'CASE', standardQuestionId: null, text: `题目${id}`, regexPatterns: [], aliases: [],
    sectionType: 'BODY', templateKey: 'theft', templateItemKey: null, locked: false, formalAnswerText: '', firstAskedAt: null,
    sortOrder, active: true, rounds: [], createdAt: null, updatedAt: null, ...extra,
  }
}
function round(answerText: string, status: 'ACTIVE' | 'DETACHED' = 'ACTIVE') {
  return { id: answerText, caseId: 'c1', sessionId: null, caseQuestionId: 'q', roundNo: 1, actualQuestionText: '', officerFragmentId: null,
    answerText, answerFragmentIds: [], status, startedAt: null, endedAt: null, createdAt: null, updatedAt: null }
}
const facts: FactItem[] = [
  { key: 'time_place', label: '案发时间与地点', value: '', status: 'missing' },
  { key: 'lock', label: '锁具情况', value: '', status: 'missing' },
]

describe('selfServiceQuestions', () => {
  it('keeps only active body questions in order, with element labels and the latest answer', () => {
    const list = selfServiceQuestions([
      question('open', 0, { sectionType: 'OPENING' }),
      question('q3', 3, { elementKey: 'lock', rounds: [round('锁了'), round('旧的回答', 'DETACHED')] }),
      question('q1', 1, { elementKey: 'time_place', formalAnswerText: '晚上七点' }),
      question('gone', 2, { active: false }),
      question('q4', 4),
    ], facts)
    expect(list.map((item) => item.id)).toEqual(['q1', 'q3', 'q4'])
    expect(list[0]).toMatchObject({ elementLabel: '案发时间与地点', elementOrdinal: 1, answer: '晚上七点', formal: true })
    expect(list[1]).toMatchObject({ elementLabel: '锁具情况', elementOrdinal: 2, answer: '锁了', formal: false })
    expect(list[2]).toMatchObject({ elementLabel: '', elementOrdinal: 0, answer: '' })
  })

  it('falls back to every active question for templates without body questions', () => {
    expect(selfServiceQuestions([question('a', 1, { sectionType: 'OPENING' })], [])).toHaveLength(1)
  })
})

describe('question navigation and stats', () => {
  const list = selfServiceQuestions([
    question('a', 1, { formalAnswerText: '十二个字的回答内容在这里' }),
    question('b', 2),
    question('c', 3, { rounds: [round('雅迪 深蓝')] }),
    question('d', 4),
  ], [])

  it('lands on the first unanswered question and wraps around when moving on', () => {
    expect(firstUnansweredIndex(list)).toBe(1)
    expect(nextUnansweredIndex(list, 1)).toBe(3)
    expect(nextUnansweredIndex(list, 3)).toBe(1)
    const done = list.map((item) => ({ ...item, answer: 'x' }))
    expect(firstUnansweredIndex(done)).toBe(3)
    expect(nextUnansweredIndex(done, 0)).toBe(-1)
  })

  it('counts answered questions and recorded characters without whitespace', () => {
    expect(answerStats(list)).toEqual({ answered: 2, unanswered: 2, chars: 16 })
  })
})

describe('display helpers', () => {
  it('renames step ③ for self-service and keeps the other steps', () => {
    expect(SELF_SERVICE_STEPS.map((step) => step.title)).toEqual(['选模板', '建档', '自助问答', '定稿校验', '签署归档'])
  })

  it('masks identity numbers and phones and formats birth dates', () => {
    expect(maskIdNumber('330502199205142319')).toBe('3305**********2319')
    expect(maskPhone('13812346721')).toBe('138****6721')
    expect(maskPhone('0572-1234567')).toBe('0572-1234567')
    expect(birthText('1992-05-14')).toBe('1992 年 5 月 14 日')
    expect(birthText('19920514')).toBe('1992 年 5 月 14 日')
    expect(circled(3)).toBe('③')
  })
})
