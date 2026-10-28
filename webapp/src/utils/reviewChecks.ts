import type { CaseSummary, FactItem } from '../types/interrogation'
import { factCoverage } from './factCoverage'

export type AutoCheckState = 'pass' | 'pending' | 'unavailable'

export interface ReviewAutoCheck {
  key: string
  title: string
  state: AutoCheckState
  detail: string
}

/** 定稿前自动校验（样板 P13）：只提示不改写，判断权在民警；尚无后端能力的项如实标为待接入。 */
export function reviewAutoChecks(facts: FactItem[], summary: Pick<CaseSummary, 'suspectName' | 'officerName'>, recorderName: string): ReviewAutoCheck[] {
  const coverage = factCoverage(facts)
  // 签署人以建档信息为准：被询问人 1 人、询问人与记录人各 1 人。
  const suspect = summary.suspectName && summary.suspectName !== '待录入' ? summary.suspectName : ''
  const officer = summary.officerName && summary.officerName !== '当前警官' ? summary.officerName : ''
  const recorder = recorderName.trim()
  const signersReady = Boolean(suspect && officer && recorder)
  return [
    {
      key: 'elements',
      title: '模板要素',
      state: coverage.missing.length ? 'pending' : 'pass',
      detail: `要素 ${coverage.covered}/${coverage.total} 已覆盖`,
    },
    { key: 'timeline', title: '时间线一致', state: 'unavailable', detail: '' },
    { key: 'homophone', title: '同音字纠错', state: 'unavailable', detail: '' },
    {
      key: 'signers',
      title: '签署人数与身份',
      state: signersReady ? 'pass' : 'pending',
      detail: `被询问人 ${suspect || '未填写'} · 询问人 ${officer || '未填写'} · 记录人 ${recorder || '未填写'}`,
    },
  ]
}
