import type { TemporaryAsrFragment } from './interrogation'

export type FormalQuestionSource = 'STANDARD' | 'CASE' | 'LIVE'
export type FormalQuestionSection = 'OPENING' | 'BODY' | 'CLOSING'
export type PendingMatchStatus = 'UNMATCHED' | 'AMBIGUOUS' | 'MATCHED_EXISTING'
export type PendingStatus = 'PENDING' | 'DEFERRED' | 'ADDED' | 'LINKED' | 'IGNORED'
export type RoundStatus = 'ACTIVE' | 'CLOSED' | 'DETACHED'
export type QARouteClass = 'MATCH_FIXED' | 'MATCH_EXISTING' | 'CREATE_LIVE_FROM_SPEECH' | 'NEEDS_REVIEW' | 'IGNORE'

export interface FormalQAUnit {
  id: string; caseId: string; sessionId: string | null; status: 'OPEN' | 'CLOSED' | 'ROUTING' | 'APPLIED' | 'NEEDS_REVIEW' | 'IGNORED' | 'ROLLED_BACK'
  classification: QARouteClass | null; rawQuestionText: string; rawAnswerText: string
  formalQuestionText: string | null; formalAnswerText: string | null; aiSuggestedQuestionText: string | null; aiSuggestedAnswerText: string | null; targetQuestionId: string | null
  candidateQuestionIds: string[]; questionFragmentIds: string[]; answerFragmentIds: string[]; controlFragmentIds?: string[]
  confidence: number | null; modelId: string | null; reasonCode: string | null
  startedAt: string | null; endedAt: string | null; createdAt: string | null; updatedAt: string | null
}

export interface FormalQuestionRound {
  id: string; caseId: string; sessionId: string | null; caseQuestionId: string; roundNo: number
  actualQuestionText: string; officerFragmentId: string | null; answerText: string; answerFragmentIds: string[]
  status: RoundStatus; startedAt: string | null; endedAt: string | null; createdAt: string | null; updatedAt: string | null
}

export interface FormalQuestion {
  id: string; caseId: string; source: FormalQuestionSource; standardQuestionId: string | null; text: string
  regexPatterns: string[]; aliases: string[]; sectionType: FormalQuestionSection; templateKey: string | null
  templateItemKey: string | null; locked: boolean; formalAnswerText: string; firstAskedAt: string | null
  sortOrder: number; active: boolean; rounds: FormalQuestionRound[]
  createdAt: string | null; updatedAt: string | null
  /** 该题归属的模板核心要素（facts 的 key，如 time / place）；后端尚未提供时为空，见 docs/backend-todo.md */
  elementKey?: string | null
}

export interface PendingFormalQuestion {
  id: string; caseId: string; sessionId: string | null; officerFragmentId: string; questionText: string
  matchStatus: PendingMatchStatus; candidateQuestionIds: string[]; bufferedAnswerText: string; bufferedFragmentIds: string[]
  status: PendingStatus; createdAt: string | null; updatedAt: string | null
}

export interface StandardQuestion {
  id: string; text: string; category: string; regexPatterns: string[]; aliases: string[]; sortOrder: number
  active: boolean; createdAt: string | null; updatedAt: string | null
}

export interface TemplateWorkspace {
  caseId: string; templateKey?: string | null; questions: FormalQuestion[]; rounds: FormalQuestionRound[]; pendingQuestions: PendingFormalQuestion[]; qaUnits: FormalQAUnit[]
}

export type LiveDialogueTurn =
  | { kind: 'QUESTION'; key: string; unitId: string; ordinal: number; text: string; startedAt: string | null }
  | { kind: 'ANSWER'; key: string; unitId: string; ordinal: number; text: string; startedAt: string | null }
  | { kind: 'UNCONFIRMED'; key: string; fragment: TemporaryAsrFragment; text: string; startedAt: string | null }
export interface CaseQuestionCreateInput { text: string; source?: FormalQuestionSource; standardQuestionId?: string | null; regexPatterns?: string[]; afterQuestionId?: string | null }
export interface CaseQuestionUpdateInput { text?: string; regexPatterns?: string[] }
export type PendingResolution =
  | { action: 'ADD'; afterQuestionId?: string | null }
  | { action: 'LINK'; caseQuestionId: string; roundMode: 'APPEND_EXISTING' | 'NEW_ROUND' }
  | { action: 'IGNORE' }
export interface RoundReassociateInput { caseQuestionId?: string | null; newQuestionText?: string | null }
export type QAUnitResolution =
  | { action: 'CREATE_LIVE'; formalQuestion?: string | null; formalAnswer?: string | null }
  | { action: 'LINK_QA'; caseQuestionId: string; formalAnswer?: string | null }
  | { action: 'LINK_ANSWER'; caseQuestionId: string; formalAnswer?: string | null }
  | { action: 'IGNORE' }
