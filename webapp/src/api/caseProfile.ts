import { getRuntimeAdapter } from '../runtime'
import type { CaseSummary, FactItem } from '../types/interrogation'
import { currentOperatorId } from './operator'

export async function updateCaseProfile(caseId: string, patch: Partial<CaseSummary>): Promise<CaseSummary> {
  return getRuntimeAdapter().invoke<CaseSummary>('case.update', {
    caseId,
    patch: patch as Record<string, unknown>,
    actorId: currentOperatorId(),
  })
}

export async function updateCaseFact(
  caseId: string,
  factKey: string,
  patch: Partial<Pick<FactItem, 'value' | 'status' | 'suggestion'>>,
): Promise<FactItem> {
  return getRuntimeAdapter().invoke<FactItem>('fact.update', {
    caseId,
    factKey,
    patch: patch as Record<string, unknown>,
    actorId: currentOperatorId(),
  })
}

export async function saveIdentityProfileFacts(caseId: string, values: Record<string, string>): Promise<void> {
  const results = await Promise.allSettled(Object.entries(values).map(([key, value]) => updateCaseFact(caseId, key, {
    value: value || '未录入', status: value ? 'confirmed' : 'missing',
  })))
  const failure = results.find((result) => result.status === 'rejected')
  if (failure?.status === 'rejected') throw failure.reason
}
