import type { CheckRule } from '../api/knowledge'
import type { FactItem } from '../types/interrogation'

/** 知识库驱动的案由专项检查（④ 定稿校验 / 定稿抽屉）。只提示、不阻断，判断权在民警。 */
export interface KnowledgeCheck {
  key: string
  state: 'pass' | 'pending'
  title: string
  detail: string
  /** 来源条目，如「知识库《盗窃电动车笔录定稿校验》v1 · rules/rule-theft-ebike.md」 */
  source: string
}

const compact = (text: string) => text.replace(/\s+/g, '').toLowerCase()

export function checkRuleSource(rule: Pick<CheckRule, 'title' | 'version' | 'sourcePath' | 'sourceRef'>): string {
  const path = rule.sourcePath || rule.sourceRef
  return `知识库《${rule.title}》v${rule.version}${path ? ` · ${path}` : ''}`
}

/**
 * 逐项核对规则：正本回答里出现任一说法，或关联要素已确认，即视为已记录。
 * 只看已摘入正本的回答——题目本身（如「当时锁了吗？」）不算已记录。
 */
export function knowledgeChecks(
  rules: CheckRule[],
  questions: { active?: boolean; formalAnswerText?: string | null }[],
  facts: FactItem[] = [],
): KnowledgeCheck[] {
  const record = compact(questions
    .filter((question) => question.active !== false)
    .map((question) => question.formalAnswerText ?? '')
    .join('\n'))
  const list: KnowledgeCheck[] = []
  for (const rule of rules) {
    const source = checkRuleSource(rule)
    for (const item of rule.items) {
      const fact = item.elementKey ? facts.find((entry) => entry.key === item.elementKey) : undefined
      const hit = item.terms.find((term) => term.trim() && record.includes(compact(term)))
      if (fact?.status === 'confirmed') {
        list.push({ key: item.key, state: 'pass', title: item.label, detail: `要素「${fact.label}」已确认`, source })
      } else if (hit) {
        list.push({ key: item.key, state: 'pass', title: item.label, detail: `正本已记录「${hit}」`, source })
      } else {
        const sample = item.terms.slice(0, 3).join('、')
        list.push({ key: item.key, state: 'pending', title: item.label, detail: `正本中未见「${sample}」等表述，可补问或如实记为未获取`, source })
      }
    }
  }
  return list
}
