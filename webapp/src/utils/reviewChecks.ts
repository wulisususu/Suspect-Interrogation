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

export interface FinalizeCheck {
  key: string
  /** pass：通过；pending：待确认（只提示，不阻断）；block：后端会拒绝定稿，必须先处理 */
  state: 'pass' | 'pending' | 'block'
  title: string
  detail: string
}

export interface FinalizeCheckInput {
  summary: Pick<CaseSummary, 'suspectName' | 'idNumber'>
  templateTitle: string
  autoChecks: ReviewAutoCheck[]
  draftAnswers: number
  unresolvedFragments: number
  unresolvedQa: number
}

/**
 * 定稿前检查清单（样板 P08 抽屉 / P13 校验页共用）。
 * 尚未接入的自动校验（时间线、同音字）不列出，避免民警误以为已经检查过。
 */
export function finalizeChecks(input: FinalizeCheckInput): FinalizeCheck[] {
  const find = (key: string) => input.autoChecks.find((item) => item.key === key && item.state !== 'unavailable')
  const list: FinalizeCheck[] = [
    { key: 'template', state: 'pass', title: '笔录格式与模板一致', detail: `《${input.templateTitle}》` },
    {
      key: 'identity',
      state: input.summary.idNumber && input.summary.suspectName ? 'pass' : 'pending',
      title: '身份信息与建档核对一致',
      detail: input.summary.idNumber && input.summary.suspectName ? '姓名、证件号码已录入' : '姓名或证件号码未录入',
    },
  ]
  for (const key of ['elements', 'timeline', 'homophone', 'signers']) {
    const item = find(key)
    if (item) list.push({ key, state: item.state === 'pass' ? 'pass' : 'pending', title: item.title, detail: item.detail })
  }
  if (input.draftAnswers) list.push({ key: 'drafts', state: 'pending', title: '录音回答未摘入正本', detail: `${input.draftAnswers} 条，未摘入的不会进入笔录` })
  if (input.unresolvedFragments) list.push({ key: 'fragments', state: 'block', title: '转写片段未处理', detail: `${input.unresolvedFragments} 条，需确认或丢弃后才能定稿` })
  if (input.unresolvedQa) list.push({ key: 'qa', state: 'block', title: '问答待处置', detail: `${input.unresolvedQa} 组，需处置后才能定稿` })
  return list
}

/** 已录音、尚未摘入正本的回答条数。 */
export function draftAnswerCount(questions: { active?: boolean; formalAnswerText?: string; rounds?: { status: string; answerText: string }[] }[]): number {
  return questions.filter((question) => question.active !== false && !question.formalAnswerText?.trim()
    && question.rounds?.some((round) => round.status !== 'DETACHED' && round.answerText?.trim())).length
}
