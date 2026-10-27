import { describe, expect, it } from 'vitest'
import type { CaseSummary } from '../types/interrogation'
import { casePhase, ledgerActions, ledgerStatus } from './caseLedger'

const c = (workflowState: string, state = 'DRAFT') => ({ id: 'C', workflowState, state }) as CaseSummary

describe('case ledger (design P20)', () => {
  it('projects workflow states onto ledger phases', () => {
    expect(casePhase(c('IDENTITY_READY'))).toBe('PREPARE')
    expect(casePhase(c('QUESTIONING'))).toBe('IN_PROGRESS')
    expect(casePhase(c('SUMMARY'))).toBe('REVIEW')
    expect(casePhase(c('FROZEN'))).toBe('SIGNING')
    expect(casePhase(c('REPORT_GENERATED'))).toBe('DONE')
  })

  it('labels statuses the way the design does', () => {
    expect(ledgerStatus(c('REPORT_GENERATED'))).toBe('已归档')
    expect(ledgerStatus(c('SIGNED'))).toBe('已签署')
    expect(ledgerStatus(c('FROZEN'))).toBe('待签署')
    expect(ledgerStatus(c('SUMMARY'))).toBe('待定稿')
    expect(ledgerStatus(c('QUESTIONING'))).toBe('进行中')
    expect(ledgerStatus(c('IDENTITY_READY'))).toBe('待准备')
  })

  it('offers the row actions for each state', () => {
    expect(ledgerActions(c('REPORT_GENERATED'))).toEqual([{ label: '导出 Word', kind: 'pending' }, { label: '导出 PDF', kind: 'pending' }])
    expect(ledgerActions(c('SIGNED'))).toEqual([{ label: '补签', kind: 'open' }, { label: '导出', kind: 'pending' }])
    expect(ledgerActions(c('SUMMARY'))).toEqual([{ label: '补录', kind: 'open' }, { label: '预览', kind: 'detail' }])
    expect(ledgerActions(c('QUESTIONING'))).toEqual([{ label: '继续办理', kind: 'open' }])
    expect(ledgerActions(c('IDENTITY_READY'))).toEqual([{ label: '继续办理', kind: 'open' }])
  })
})
