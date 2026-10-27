import { describe, expect, it } from 'vitest'
import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { factValue, formatRecordTime, recordWordCount, volumeNumber } from './recordPaper'

const fact = (key: string, value: string) => ({ key, label: key, value, status: 'confirmed' }) as FactItem

describe('record paper helpers', () => {
  it('treats the 未录入 placeholder and blanks as missing', () => {
    expect(factValue([fact('a', '未录入')], 'a')).toBe('未填写')
    expect(factValue([fact('a', '  ')], 'a', '身份证')).toBe('身份证')
    expect(factValue([fact('a', ' 一楼报案大厅 ')], 'a')).toBe('一楼报案大厅')
    expect(factValue([], 'a')).toBe('未填写')
  })

  it('formats empty timestamps as 未记录', () => {
    expect(formatRecordTime(null)).toBe('未记录')
    expect(formatRecordTime(undefined)).toBe('未记录')
    expect(formatRecordTime(0)).toBe('未记录')
  })

  it('counts trimmed answer characters only', () => {
    const questions = [{ formalAnswerText: ' 你好 ' }, { formalAnswerText: null }, { formalAnswerText: '是的' }] as unknown as FormalQuestion[]
    expect(recordWordCount(questions)).toBe(4)
  })

  it('never invents a volume number without a configured prefix', () => {
    expect(volumeNumber(null, 'CASE-20261026-D5DA12')).toBe('卷号待分配')
    expect(volumeNumber('', 'CASE-20261026-D5DA12')).toBe('卷号待分配')
    expect(volumeNumber('2026-乙', 'CASE-20261026-D5DA12')).toBe('2026-乙-61026512-01')
  })
})
