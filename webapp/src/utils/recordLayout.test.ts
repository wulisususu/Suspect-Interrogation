import { describe, expect, it } from 'vitest'
import { RECORD_FONT_PX, RECORD_LINE_PX, breakLines, estimateTextWidth, paginateRecord, qaRows, wrapFieldRows, type RecordRow } from './recordLayout'

const em = RECORD_FONT_PX
const lines = (count: number): RecordRow[] => Array.from({ length: count }, (_, index) => ({ kind: 'line', text: String(index), justify: false }))

describe('breakLines', () => {
  it('fits 33 Song-typeface characters per line, like the station print', () => {
    const text = '我'.repeat(70)
    const result = breakLines(text, estimateTextWidth, RECORD_LINE_PX)
    expect(result.map((line) => line.length)).toEqual([33, 33, 4])
  })

  it('never starts a line with closing punctuation', () => {
    const text = '我'.repeat(33) + '，后面的话'
    const result = breakLines(text, estimateTextWidth, RECORD_LINE_PX)
    expect(result[1]!.startsWith('我，')).toBe(true)
    expect(result.every((line) => !/^[，。、；：？！）》”]/.test(line))).toBe(true)
  })

  it('never ends a line with an opening bracket', () => {
    const text = '我'.repeat(32) + '《行政案件权利义务告知书》'
    const result = breakLines(text, estimateTextWidth, RECORD_LINE_PX)
    expect(result[0]!.endsWith('《')).toBe(false)
    expect(result[1]!.startsWith('《')).toBe(true)
  })

  it('keeps an ID number on one line', () => {
    const result = breakLines('我'.repeat(25) + '320602199003051234', estimateTextWidth, RECORD_LINE_PX)
    expect(result).toEqual(['我'.repeat(25), '320602199003051234'])
  })

  it('hard-breaks a run of digits longer than a line', () => {
    const result = breakLines('1'.repeat(100), estimateTextWidth, 10 * em)
    expect(result.every((line) => estimateTextWidth(line) <= 10 * em)).toBe(true)
    expect(result.join('')).toBe('1'.repeat(100))
  })
})

describe('qaRows', () => {
  it('prefixes 问/答, justifies inner lines and starts a new row at answer line breaks', () => {
    const rows = qaRows([{ text: '你的基本情况？', formalAnswerText: '我'.repeat(40) + '\n第二段' }], estimateTextWidth)
    expect(rows.map((row) => row.kind === 'line' && [row.text.slice(0, 2), row.justify])).toEqual([['问：', false], ['答：', true], ['我我', false], ['第二', false]])
  })

  it('does not stretch a short line left behind by an ID number that wrapped', () => {
    const rows = qaRows([{ text: '你的基本情况？', formalAnswerText: '我'.repeat(20) + '，身份证号码320602199003051234。' }], estimateTextWidth)
    expect(rows[1]).toMatchObject({ kind: 'line', justify: false })
    expect(rows[2]).toMatchObject({ kind: 'line', text: '320602199003051234。' })
  })
})

describe('wrapFieldRows', () => {
  it('continues an over-long address on a full-width underlined row', () => {
    const rows = wrapFieldRows([{ kind: 'fields', fields: [{ label: '现住址', value: '江苏省'.repeat(15) }] }], estimateTextWidth)
    expect(rows.map((row) => row.kind)).toEqual(['fields', 'fill'])
  })
})

describe('paginateRecord', () => {
  it('puts the 10 header rows and a blank row on page one, leaving 8 rows for questions (as on the sample)', () => {
    const header = lines(10)
    const pages = paginateRecord(header, lines(8 + 22 + 1))
    expect(pages.map((page) => page.rows.length)).toEqual([19, 22, 1])
    expect(pages[0]!.rows[10]).toEqual({ kind: 'blank' })
  })

  it('reserves footer rows on the last page or opens a new one', () => {
    expect(paginateRecord(lines(10), lines(3), 5).map((page) => page.footerAtRow)).toEqual([14])
    expect(paginateRecord(lines(10), lines(5), 5).map((page) => page.footerAtRow)).toEqual([null, 0])
  })
})
