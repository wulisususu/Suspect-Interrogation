import type { FactItem } from '../types/interrogation'

/** 模板核心要素（案情要素）；其余事实是笔录抬头信息，不计入要素覆盖。 */
export const CORE_FACT_KEYS = ['time', 'place', 'motive', 'method', 'process', 'evidence', 'after'] as const

export function coreFacts(facts: FactItem[]): FactItem[] {
  return CORE_FACT_KEYS
    .map((key) => facts.find((item) => item.key === key))
    .filter((item): item is FactItem => Boolean(item))
}

export interface FactCoverage {
  total: number
  covered: number
  missing: FactItem[]
}

/** 要素覆盖：已确认的核心要素计入覆盖，其余（待补 / 未获取 / 冲突）列为缺项。 */
export function factCoverage(facts: FactItem[]): FactCoverage {
  const core = coreFacts(facts)
  const missing = core.filter((item) => item.status !== 'confirmed')
  return { total: core.length, covered: core.length - missing.length, missing }
}
