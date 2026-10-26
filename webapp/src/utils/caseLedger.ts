import type { CaseSummary } from '../types/interrogation'

export type CasePhase = 'PREPARE' | 'IN_PROGRESS' | 'REVIEW' | 'SIGNING' | 'DONE'

/** 后端工作流 → 台账阶段（与 flow/steps 的步骤投影同源，只是粒度更粗）。 */
export function casePhase(item: CaseSummary): CasePhase {
  const workflow = item.workflowState || ''
  if (workflow === 'REPORT_GENERATED' || item.state === 'ARCHIVED' || item.state === 'COMPLETED') return 'DONE'
  if (workflow === 'FROZEN' || workflow === 'SIGNED' || item.state === 'SIGNING') return 'SIGNING'
  if (workflow === 'SUMMARY' || item.state === 'REVIEWING') return 'REVIEW'
  if (workflow === 'QUESTIONING' || workflow === 'PAUSED' || item.state === 'INTERROGATING') return 'IN_PROGRESS'
  return 'PREPARE'
}

export function ledgerStatus(item: CaseSummary): string {
  const phase = casePhase(item)
  if (phase === 'SIGNING') return item.workflowState === 'SIGNED' ? '已签署' : '待签署'
  return { PREPARE: '待准备', IN_PROGRESS: '进行中', REVIEW: '待定稿', DONE: '已归档' }[phase]
}

/** 台账行操作（样板 P20）：open 进入办理，detail 打开案件详情，pending 为尚未接入的导出类操作。 */
export interface LedgerAction {
  label: string
  kind: 'open' | 'detail' | 'pending'
}

export function ledgerActions(item: CaseSummary): LedgerAction[] {
  const phase = casePhase(item)
  if (phase === 'DONE') return [{ label: '导出 Word', kind: 'pending' }, { label: '导出 PDF', kind: 'pending' }]
  if (phase === 'SIGNING') return [{ label: '补签', kind: 'open' }, { label: '导出', kind: 'pending' }]
  if (phase === 'REVIEW') return [{ label: '补录', kind: 'open' }, { label: '预览', kind: 'detail' }]
  return [{ label: '继续办理', kind: 'open' }]
}
