import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/** 笔录纸面取事实值：后端用「未录入」占位，纸面上统一显示为 fallback。 */
export function factValue(facts: FactItem[], key: string, fallback = '未填写'): string {
  const value = facts.find((item) => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : fallback
}

export function formatRecordTime(ms?: number | null): string {
  return ms ? new Date(ms).toLocaleString('zh-CN', { hour12: false }) : '未记录'
}

export function recordWordCount(questions: FormalQuestion[]): number {
  return questions.reduce((sum, item) => sum + (item.formalAnswerText?.trim().length || 0), 0)
}

/** 卷号字头由部署配置给出；未配置时如实显示待分配，不在前端编造卷号。 */
export function volumeNumber(prefix: string | null | undefined, caseId: string): string {
  if (!prefix) return '卷号待分配'
  const digits = caseId.replace(/\D/g, '').slice(-8) || '0000'
  return `${prefix}-${digits}-01`
}
