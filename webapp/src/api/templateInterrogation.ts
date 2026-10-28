import type { AxiosResponse } from 'axios'

import {
  startBrowserQuestionPreparationCapture,
  stopBrowserQuestionPreparationCapture,
} from '../audio/browserAsrCapture'
import { audioInputMode } from '../config/audioInput'
import { runtimeConfig } from '../config/runtime'
import type { BackendEnvelope } from '../types/interrogation'
import type {
  CaseQuestionCreateInput,
  CaseQuestionUpdateInput,
  FormalQuestion,
  FormalQuestionRound,
  PendingFormalQuestion,
  QAUnitResolution,
  RoundReassociateInput,
  StandardQuestion,
  TemplateWorkspace,
} from '../types/templateInterrogation'
import { http } from './http'

export interface QuestionDictationStatus {
  caseId: string
  active: boolean
  mode: 'QUESTION_PREP'
  captureSessionId: string | null
  interrogationSessionId: null
  status: 'IDLE' | 'CAPTURING' | 'STOPPED'
  sampleRate: number
  text: string
  lastError: string | null
}

function unwrap<T>(response: AxiosResponse<BackendEnvelope<T>>): T {
  const body = response.data
  if (!body.ok) throw new Error(body.message || body.code || '模板笔录接口调用失败')
  return body.data
}

export async function fetchTemplateWorkspace(caseId: string): Promise<TemplateWorkspace> {
  return unwrap(await http.get<BackendEnvelope<TemplateWorkspace>>(`/api/v1/cases/${encodeURIComponent(caseId)}/template-workspace`))
}

export async function fetchQuestionLibrary(category?: string): Promise<StandardQuestion[]> {
  return unwrap(await http.get<BackendEnvelope<StandardQuestion[]>>('/api/v1/question-library', {
    params: category ? { category } : undefined,
  }))
}

export async function startQuestionPreparationDictation(caseId: string): Promise<QuestionDictationStatus> {
  const status = unwrap(await http.post<BackendEnvelope<QuestionDictationStatus>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/asr/question-preparation/start`,
  ))
  if (audioInputMode !== 'BROWSER') return status

  try {
    await startBrowserQuestionPreparationCapture(
      caseId,
      status.captureSessionId || 'question-preparation',
      runtimeConfig.apiBaseUrl,
    )
    return status
  } catch (error) {
    await http.post(`/api/v1/cases/${encodeURIComponent(caseId)}/asr/question-preparation/stop`).catch(() => undefined)
    await stopBrowserQuestionPreparationCapture().catch(() => undefined)
    throw error
  }
}

export async function stopQuestionPreparationDictation(caseId: string): Promise<QuestionDictationStatus> {
  try {
    return unwrap(await http.post<BackendEnvelope<QuestionDictationStatus>>(
      `/api/v1/cases/${encodeURIComponent(caseId)}/asr/question-preparation/stop`,
    ))
  } finally {
    if (audioInputMode === 'BROWSER') await stopBrowserQuestionPreparationCapture().catch(() => undefined)
  }
}

export async function createCaseQuestion(caseId: string, input: CaseQuestionCreateInput): Promise<FormalQuestion> {
  return unwrap(await http.post<BackendEnvelope<FormalQuestion>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions`,
    {
      text: input.text,
      source: input.source ?? 'CASE',
      standardQuestionId: input.standardQuestionId ?? null,
      regexPatterns: input.regexPatterns ?? [],
      afterQuestionId: input.afterQuestionId ?? null,
    },
  ))
}

export async function createLiveQuestionFromFragment(caseId: string, fragmentId: string, afterQuestionId?: string | null): Promise<unknown> {
  return unwrap(await http.post<BackendEnvelope<unknown>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions/from-fragment`,
    { fragmentId, afterQuestionId: afterQuestionId ?? null },
  ))
}

export async function updateCaseQuestion(caseId: string, questionId: string, input: CaseQuestionUpdateInput): Promise<FormalQuestion> {
  return unwrap(await http.patch<BackendEnvelope<FormalQuestion>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions/${encodeURIComponent(questionId)}`,
    input,
  ))
}

export async function reorderCaseQuestions(caseId: string, questionIds: string[]): Promise<FormalQuestion[]> {
  return unwrap(await http.post<BackendEnvelope<FormalQuestion[]>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions/reorder`,
    { questionIds },
  ))
}

export async function addPendingQuestion(caseId: string, pendingId: string, afterQuestionId?: string | null): Promise<FormalQuestionRound> {
  return unwrap(await http.post<BackendEnvelope<FormalQuestionRound>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/pending-questions/${encodeURIComponent(pendingId)}/add`,
    { afterQuestionId: afterQuestionId ?? null },
  ))
}

export async function linkPendingQuestion(
  caseId: string,
  pendingId: string,
  caseQuestionId: string,
  roundMode: 'APPEND_EXISTING' | 'NEW_ROUND',
): Promise<FormalQuestionRound> {
  return unwrap(await http.post<BackendEnvelope<FormalQuestionRound>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/pending-questions/${encodeURIComponent(pendingId)}/link`,
    { caseQuestionId, roundMode },
  ))
}

export async function ignorePendingQuestion(caseId: string, pendingId: string): Promise<PendingFormalQuestion> {
  return unwrap(await http.post<BackendEnvelope<PendingFormalQuestion>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/pending-questions/${encodeURIComponent(pendingId)}/ignore`,
  ))
}

export async function reassociateRound(caseId: string, roundId: string, input: RoundReassociateInput): Promise<FormalQuestionRound> {
  return unwrap(await http.post<BackendEnvelope<FormalQuestionRound>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/rounds/${encodeURIComponent(roundId)}/reassociate`,
    input,
  ))
}

export async function updateRoundAnswer(caseId: string, roundId: string, answerText: string): Promise<FormalQuestionRound> {
  return unwrap(await http.patch<BackendEnvelope<FormalQuestionRound>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/rounds/${encodeURIComponent(roundId)}`,
    { answerText },
  ))
}

export async function upsertQuestionAnswer(caseId: string, questionId: string, answerText: string): Promise<FormalQuestionRound> {
  return unwrap(await http.put<BackendEnvelope<FormalQuestionRound>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions/${encodeURIComponent(questionId)}/answer`,
    { answerText },
  ))
}

export interface AttachAnswerOptions {
  /** 只挂成待摘入草稿，不写入正本 */
  draft?: boolean
  /** 重录：替换原草稿而不是追加 */
  replace?: boolean
}

export async function attachQuestionAnswerFragments(caseId: string, questionId: string, fragmentIds: string[], options: AttachAnswerOptions = {}): Promise<FormalQuestionRound> {
  return unwrap(await http.post<BackendEnvelope<FormalQuestionRound>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions/${encodeURIComponent(questionId)}/answer-fragments`,
    { fragmentIds, ...(options.draft ? { draft: true } : {}), ...(options.replace ? { replace: true } : {}) },
  ))
}

export async function saveQuestionToLibrary(caseId: string, questionId: string, category = '通用'): Promise<StandardQuestion> {
  return unwrap(await http.post<BackendEnvelope<StandardQuestion>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/questions/${encodeURIComponent(questionId)}/save-to-library`,
    { category },
  ))
}


export async function resolveQaUnit(caseId: string, qaUnitId: string, resolution: QAUnitResolution): Promise<unknown> {
  return unwrap(await http.post<BackendEnvelope<unknown>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/qa-units/${encodeURIComponent(qaUnitId)}/resolve`,
    resolution,
  ))
}

export async function rollbackQaUnit(caseId: string, qaUnitId: string): Promise<unknown> {
  return unwrap(await http.post<BackendEnvelope<unknown>>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/qa-units/${encodeURIComponent(qaUnitId)}/rollback`,
  ))
}


export async function ensureFormalRecord(caseId: string): Promise<TemplateWorkspace> {
  return unwrap(await http.post<BackendEnvelope<TemplateWorkspace>>(`/api/v1/cases/${encodeURIComponent(caseId)}/formal-record/ensure`))
}

export async function deactivateCaseQuestion(caseId: string, questionId: string): Promise<FormalQuestion> {
  return unwrap(await http.delete<BackendEnvelope<FormalQuestion>>(`/api/v1/cases/${encodeURIComponent(caseId)}/questions/${encodeURIComponent(questionId)}`))
}
