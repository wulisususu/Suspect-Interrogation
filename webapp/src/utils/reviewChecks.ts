import type { FactItem, VoiceprintReadiness } from '../types/interrogation'
import { factCoverage } from './factCoverage'

export type AutoCheckState = 'pass' | 'pending' | 'unavailable'

export interface ReviewAutoCheck {
  key: string
  title: string
  state: AutoCheckState
  detail: string
}

/** 定稿前自动校验（样板 P13）：只提示不改写，判断权在民警；尚无后端能力的项如实标为待接入。 */
export function reviewAutoChecks(facts: FactItem[], readiness: VoiceprintReadiness): ReviewAutoCheck[] {
  const coverage = factCoverage(facts)
  const signersReady = readiness.suspectReady && readiness.interrogatorReady
  // 审讯结束后已无 active session，后端回退到本场审讯开始时的角色绑定。
  // 这里如实区分"当前审讯"与"本场审讯（已结束）"，避免把回退读成进行中的绑定。
  const officerBinding = !readiness.interrogatorReady
    ? '未绑定'
    : readiness.roleBindingScope === 'LAST_SESSION' ? '本场审讯已绑定' : '已绑定'
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
      detail: `被询问人 ${readiness.suspectReady ? '已注册' : '未注册'} · 主审民警 ${officerBinding}`,
    },
  ]
}
