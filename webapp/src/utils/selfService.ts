import { FLOW_STEPS, type FlowStepMeta } from '../flow/steps'
import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * 自助模式（当事人本人作答）的纯计算部分，页面只负责呈现。
 *
 * 本人只回答模板正文题（开场告知与结尾确认属于民警的规定动作，不交给本人）；
 * 回答以「待摘入」草稿挂在题上，正本仍由民警核对后摘入。
 */

/** 步骤条与人工模式同一套五步，③在自助模式下叫「自助问答」。 */
export const SELF_SERVICE_STEPS: readonly FlowStepMeta[] = FLOW_STEPS.map((step) => (step.key === 'dictation'
  ? { ...step, title: '自助问答', hint: '转写文字实时上屏 · 确认后进入下一题' }
  : step))

export interface SelfQuestion {
  id: string
  text: string
  elementKey: string
  /** 「核心要素 ③ 锁具情况」里的要素名；题目没有要素归属时为空 */
  elementLabel: string
  /** 要素在模板里的序号（从 1 开始），没有要素归属时为 0 */
  elementOrdinal: number
  answer: string
  /** 回答已由民警摘入正本（本人再重录也只会生成新的草稿） */
  formal: boolean
}

export function latestAnswer(question: Pick<FormalQuestion, 'formalAnswerText' | 'rounds'>): string {
  const formal = question.formalAnswerText?.trim()
  if (formal) return formal
  const round = [...(question.rounds ?? [])].reverse().find((item) => item.status !== 'DETACHED' && item.answerText?.trim())
  return round?.answerText.trim() || ''
}

export function selfServiceQuestions(questions: FormalQuestion[], facts: FactItem[]): SelfQuestion[] {
  const active = questions.filter((item) => item.active !== false).sort((a, b) => a.sortOrder - b.sortOrder)
  const body = active.filter((item) => item.sectionType === 'BODY')
  const elementKeys: string[] = []
  for (const item of body) if (item.elementKey && !elementKeys.includes(item.elementKey)) elementKeys.push(item.elementKey)
  return (body.length ? body : active).map((item) => ({
    id: item.id,
    text: item.text,
    elementKey: item.elementKey || '',
    elementLabel: (item.elementKey && facts.find((fact) => fact.key === item.elementKey)?.label) || '',
    elementOrdinal: item.elementKey ? elementKeys.indexOf(item.elementKey) + 1 : 0,
    answer: latestAnswer(item),
    formal: Boolean(item.formalAnswerText?.trim()),
  }))
}

/** 进入问答时落在第一道还没回答的题；全部答完则停在最后一题。 */
export function firstUnansweredIndex(list: SelfQuestion[]): number {
  const index = list.findIndex((item) => !item.answer)
  return index >= 0 ? index : Math.max(0, list.length - 1)
}

/** 从 from 往后找下一道没回答的题，后面都答了再从头找；全部答完返回 -1。 */
export function nextUnansweredIndex(list: SelfQuestion[], from: number): number {
  for (let step = 1; step <= list.length; step += 1) {
    const index = (from + step) % list.length
    if (!list[index]?.answer) return index
  }
  return -1
}

export function answerStats(list: SelfQuestion[]) {
  const answered = list.filter((item) => item.answer)
  return {
    answered: answered.length,
    unanswered: list.length - answered.length,
    chars: answered.reduce((sum, item) => sum + item.answer.replace(/\s/g, '').length, 0),
  }
}

export function circled(index: number): string {
  return index >= 1 && index <= 20 ? String.fromCharCode(0x245f + index) : String(index)
}

export function maskIdNumber(value?: string): string {
  const id = (value || '').trim()
  return id.length > 8 ? `${id.slice(0, 4)}${'*'.repeat(id.length - 8)}${id.slice(-4)}` : id
}

export function maskPhone(value?: string): string {
  const phone = (value || '').trim()
  return /^\d{11}$/.test(phone) ? `${phone.slice(0, 3)}****${phone.slice(-4)}` : phone
}

/** 「1992-05-14」→「1992 年 5 月 14 日」，其它格式原样返回。 */
export function birthText(value?: string): string {
  const match = /^(\d{4})-?(\d{1,2})-?(\d{1,2})/.exec(value || '')
  return match ? `${match[1]} 年 ${Number(match[2])} 月 ${Number(match[3])} 日` : value || ''
}
