import { getRuntimeAdapter } from '../runtime'
import type { DocumentSigningState } from '../types/interrogation'

/**
 * 归档结案
 *
 * 后端在签名齐备后允许 SIGNED → REPORT_GENERATED，这是主线最后一步的状态跃迁。
 * 生成正式件（PDF/Word）目前由前端完成：PDF 走打印视图，Word 走文字版下载。
 */
export function markReportGenerated(caseId: string): Promise<DocumentSigningState> {
  return getRuntimeAdapter().invoke<DocumentSigningState>('case.report.generated', { caseId }, { timeoutMs: 60_000 })
}
