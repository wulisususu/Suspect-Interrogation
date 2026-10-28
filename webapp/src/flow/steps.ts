/**
 * 流程步骤 · 唯一事实源
 *
 * 前端不再用并列 tab 表达办理顺序，所有页面从这里的快照推导自己在哪一步。
 * 后端工作流（linux/backend/app/workflow/state.py）是线性的：
 *   INIT → IDENTITY_REQUIRED → IDENTITY_READY → CASE_CREATED
 *        → QUESTIONING ⇄ PAUSED → SUMMARY → FROZEN → SIGNED → REPORT_GENERATED
 * 这里只做「状态 → 步骤」的投影，不复制状态机，避免两套真相。
 */

export type FlowStepKey = 'template' | 'intake' | 'dictation' | 'review' | 'signing'

/** 笔录页内部的呈现形态：问答对应③、校验对应④，签署与归档导出同属⑤。 */
export type RecordMode = 'interrogation' | 'review' | 'sign' | 'archive'

export interface FlowStepMeta {
  key: FlowStepKey
  /** ①–⑤，与样板一致 */
  ordinal: string
  title: string
  /** 步骤条悬停与只读态的说明 */
  hint: string
}

export const FLOW_STEPS: readonly FlowStepMeta[] = [
  { key: 'template', ordinal: '①', title: '选模板', hint: '系统推荐不代替民警选择 · 可跳过模板直接空白笔录' },
  { key: 'intake', ordinal: '②', title: '建档', hint: '身份证读卡自动填入 · 身份证上没有的信息手工补填' },
  { key: 'dictation', ordinal: '③', title: '问答录入', hint: '左侧逐题成卡，右侧实时成文' },
  { key: 'review', ordinal: '④', title: '定稿校验', hint: '定稿后笔录冻结 · 未获取项已如实标注' },
  { key: 'signing', ordinal: '⑤', title: '签署归档', hint: '文末热区点击即弹窗签名 / 捺印 · 完成后打印 2 份装卷' },
] as const

export interface FlowSnapshot {
  /** 后端 workflowState；缺失时按前端已知条件退化推导 */
  workflowState?: string | null
  hasTemplate: boolean
  identityReady: boolean
  hasQuestions: boolean
  frozen: boolean
  signed: boolean
  archived: boolean
}

export interface FlowProgress {
  /** 已完成的步骤 */
  completed: FlowStepKey[]
  /** 当前可进入的步骤（点击拦截用） */
  reachable: FlowStepKey[]
  /** 未指定时的默认落点：第一个未完成的步骤 */
  suggested: FlowStepKey
}

const ORDER: FlowStepKey[] = FLOW_STEPS.map((step) => step.key)

const WORKFLOW_TO_STEP: Record<string, FlowStepKey> = {
  INIT: 'template',
  IDENTITY_REQUIRED: 'intake',
  IDENTITY_READY: 'intake',
  CASE_CREATED: 'intake',
  QUESTIONING: 'dictation',
  PAUSED: 'dictation',
  SUMMARY: 'review',
  FROZEN: 'signing',
  SIGNED: 'signing',
  REPORT_GENERATED: 'signing',
}

/** 后端状态下，该案例所处的最远步骤（用于覆盖前端推导结果）。 */
export function stepFromWorkflowState(workflowState?: string | null): FlowStepKey | null {
  if (!workflowState) return null
  return WORKFLOW_TO_STEP[workflowState] ?? null
}

export function resolveFlowProgress(snapshot: FlowSnapshot): FlowProgress {
  const { hasTemplate, identityReady, hasQuestions, frozen, archived } = snapshot

  const intakeDone = hasTemplate && identityReady
  const dictationDone = intakeDone && hasQuestions && frozen
  // 问答以冻结收尾，冻结即视为定稿校验完成。
  const reviewDone = dictationDone

  const doneByKey: Record<FlowStepKey, boolean> = {
    template: hasTemplate,
    intake: intakeDone,
    dictation: dictationDone,
    review: reviewDone,
    // 签署归档以确认归档收尾；只签了名还停在⑤。
    signing: archived,
  }
  const completed = ORDER.filter((key) => doneByKey[key])

  // 进入条件：只要案件已经出题，问答与定稿就该走得进去——建档要素缺失
  // 不拦办理，由④定稿校验页自己把缺项标出来。
  const reachable: FlowStepKey[] = ['template', 'intake']
  if (intakeDone || hasQuestions) reachable.push('dictation')
  if (hasQuestions || frozen) reachable.push('review')
  if (frozen) reachable.push('signing')

  const suggested = ORDER.find((key) => !doneByKey[key]) ?? 'signing'

  return { completed, reachable, suggested }
}

export function stepKeyForMode(mode: RecordMode): FlowStepKey {
  if (mode === 'review') return 'review'
  if (mode === 'sign' || mode === 'archive') return 'signing'
  return 'dictation'
}

/** 已归档的案件进入⑤时直接展示归档导出，未归档时展示签署页。 */
export function modeForStep(key: FlowStepKey, archived = false): RecordMode {
  if (key === 'review') return 'review'
  if (key === 'signing') return archived ? 'archive' : 'sign'
  return 'interrogation'
}

export function stepMeta(key: FlowStepKey): FlowStepMeta {
  return FLOW_STEPS.find((step) => step.key === key) ?? FLOW_STEPS[0]!
}

export function stepIndex(key: FlowStepKey): number {
  return ORDER.indexOf(key)
}

/** 工作台主体区域的页面：①选模板、②建档（单页），③–⑤共用笔录页。 */
export type WorkspacePage = 'template' | 'profile' | 'interrogation'

export function pageForStep(key: FlowStepKey): WorkspacePage {
  if (key === 'template') return 'template'
  if (key === 'intake') return 'profile'
  return 'interrogation'
}
