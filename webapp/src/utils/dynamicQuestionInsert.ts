import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * 「案件动态问答区」的追加落点：新的动态问题应该插到哪一条问题之后。
 *
 * 规则：动态区已有问题（BODY）时追加到最后一条 BODY 之后，保证新问题出现在
 * 动态区末尾、结束语之前；动态区为空时落到最后一条开场问题（OPENING）之后，
 * 于是它成为动态区的第一条；笔录里一条问题都没有时返回 null。
 */
export function dynamicAppendAfterId(questions: FormalQuestion[]): string | null {
  const ordered = [...questions].sort((a, b) => a.sortOrder - b.sortOrder)
  const lastBody = ordered.filter((q) => q.sectionType === 'BODY').at(-1)
  if (lastBody) return lastBody.id
  const lastOpening = ordered.filter((q) => q.sectionType === 'OPENING').at(-1)
  return lastOpening ? lastOpening.id : null
}
