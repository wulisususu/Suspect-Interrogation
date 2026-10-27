/**
 * 流程步骤 · 唯一事实源
 *
 * 前端不再用并列 tab 表达办理顺序，所有页面从这里的快照推导自己在哪一步。
 * 后端工作流（linux/backend/app/workflow/state.py）是线性的：
 *   INIT → IDENTITY_REQUIRED → IDENTITY_READY → CASE_CREATED
 *        → QUESTIONING ⇄ PAUSED → SUMMARY → FROZEN → SIGNED → REPORT_GENERATED
 * 这里只做「状态 → 步骤」的投影，不复制状态机，避免两套真相。
 */

export type FlowStepKey = 'template' | 'intake' | 'dictation' | 'review' | 'signing' | 'archive'

/** 笔录页内部的三种呈现形态，与步骤 3/4/5 一一对应。 */
export type RecordMode = 'interrogation' | 'review' | 'sign' | 'archive'

export interface FlowStepMeta {
  key: FlowStepKey
  /** ①–⑥，与样板一致 */
  ordinal: string
  title: string
  /** 步骤条悬停与只读态的说明 */
  hint: string
}

export const FLOW_STEPS: readonly FlowStepMeta[] = [
  { key: 'template', ordinal: '①', title: '选模板', hint: '按案件类型选定笔录模板，决定要素与预设问题' },
  { key: 'intake', ordinal: '②', title: '建档', hint: '读卡核对身份、注册声纹、确认设备就绪' },
  { key: 'dictation', ordinal: '③', title: '问答录入', hint: '左侧逐题成卡，右侧实时成文' },
  { key: 'review', ordinal: '④', title: '定稿校验', hint: '核对核心要素，补齐缺项后冻结笔录' },
  { key: 'signing', ordinal: '⑤', title: '签署归档', hint: '签名、捺印、民警签章后打印装卷' },
  { key: 'archive', ordinal: '⑥', title: '归档导出', hint: '生成归档正式件，按需导出 Word 或 PDF' },
] as const

export interface FlowSnapshot {
  /** 后端 workflowState；缺失时按前端已知条件退化推导 */
  workflowState?: string | null
  hasTemplate: boolean
  identityReady: boolean
  voiceprintReady: boolean
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
  REPORT_GENERATED: 'archive',
}

/** 后端状态下，该案例所处的最远步骤（用于覆盖前端推导结果）。 */
export function stepFromWorkflowState(workflowState?: string | null): FlowStepKey | null {
  if (!workflowState) return null
  return WORKFLOW_TO_STEP[workflowState] ?? null
}

export function resolveFlowProgress(snapshot: FlowSnapshot): FlowProgress {
  const { hasTemplate, identityReady, voiceprintReady, hasQuestions, frozen, signed, archived } = snapshot

  const intakeDone = hasTemplate && identityReady && voiceprintReady
  const dictationDone = intakeDone && hasQuestions && frozen
  // 问答以冻结收尾，冻结即视为定稿校验完成。
  const reviewDone = dictationDone
  const archiveDone = reviewDone && archived

  const doneByKey: Record<FlowStepKey, boolean> = {
    template: hasTemplate,
    intake: intakeDone,
    dictation: dictationDone,
    review: reviewDone,
    signing: signed || archived,
    archive: archiveDone,
  }
  const completed = ORDER.filter((key) => doneByKey[key])

  // 进入条件：只要案件已经出题，问答与定稿就该走得进去——建档要素缺失
  // 不拦办理，由④定稿校验页自己把缺项标出来。
  const reachable: FlowStepKey[] = ['template', 'intake']
  if (intakeDone || hasQuestions) reachable.push('dictation')
  if (hasQuestions || frozen) reachable.push('review')
  if (frozen) reachable.push('signing')
  // 归档导出只在真正归档后开放；签名齐备后在⑤页确认归档。
  if (archived) reachable.push('archive')

  const suggested = ORDER.find((key) => !doneByKey[key]) ?? 'archive'

  return { completed, reachable, suggested }
}

export function stepKeyForMode(mode: RecordMode): FlowStepKey {
  if (mode === 'review') return 'review'
  if (mode === 'sign') return 'signing'
  if (mode === 'archive') return 'archive'
  return 'dictation'
}

export function modeForStep(key: FlowStepKey): RecordMode {
  if (key === 'review') return 'review'
  if (key === 'signing') return 'sign'
  if (key === 'archive') return 'archive'
  return 'interrogation'
}

export function stepMeta(key: FlowStepKey): FlowStepMeta {
  return FLOW_STEPS.find((step) => step.key === key) ?? FLOW_STEPS[0]!
}

export function stepIndex(key: FlowStepKey): number {
  return ORDER.indexOf(key)
}

/** 工作台主体区域的页面；建档步骤下有询问准备 / 身份信息 / 声纹注册三个子页。 */
export type WorkspacePage = 'template' | 'prepare' | 'profile' | 'interrogation' | 'moss' | 'voiceprint'

const INTAKE_PAGES: readonly WorkspacePage[] = ['prepare', 'profile', 'voiceprint']

/** 步骤 → 主体页面。进入建档时保留当前所在的建档子页。 */
export function pageForStep(key: FlowStepKey, current: WorkspacePage): WorkspacePage {
  if (key === 'template') return 'template'
  if (key === 'intake') return INTAKE_PAGES.includes(current) ? current : 'prepare'
  return 'interrogation'
}
