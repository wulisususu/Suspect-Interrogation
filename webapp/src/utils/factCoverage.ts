import type { FactItem } from '../types/interrogation'

/** 模板核心要素（案情要素）；其余事实是笔录抬头信息，不计入要素覆盖。 */
export const CORE_FACT_KEYS = ['time', 'place', 'motive', 'method', 'process', 'evidence', 'after'] as const

export function coreFacts(facts: FactItem[]): FactItem[] {
  return CORE_FACT_KEYS
    .map((key) => facts.find((item) => item.key === key))
    .filter((item): item is FactItem => Boolean(item))
}
