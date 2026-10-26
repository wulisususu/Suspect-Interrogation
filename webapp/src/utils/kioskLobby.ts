import type { CaseSummary } from '../types/interrogation'

/**
 * 未完成办理：已开始但未归档的案件。
 * 尚未进入任何办理环节（workflowState 为空或 INIT）的视为草稿，不计入（样板 P23）。
 */
export function unfinishedCases(cases: CaseSummary[]): CaseSummary[] {
  return cases.filter((item) => {
    const workflow = item.workflowState || 'INIT'
    return workflow !== 'INIT' && workflow !== 'REPORT_GENERATED' && item.state !== 'ARCHIVED'
  })
}
