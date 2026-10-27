import { getRuntimeAdapter, RuntimeAdapterError } from '../runtime'
import type { DocumentSignerRole, DocumentSigningState } from '../types/interrogation'
import { currentOperatorId } from './operator'

export async function fetchDocumentSigningState(caseId: string): Promise<DocumentSigningState | null> {
  try {
    return await getRuntimeAdapter().invoke<DocumentSigningState | null>('document.signing.get', { caseId })
  } catch (error) {
    if (error instanceof RuntimeAdapterError && (error.state === 'NOT_CONFIGURED' || error.state === 'MODEL_NOT_INSTALLED')) return null
    throw error
  }
}

export function freezeDocument(caseId: string): Promise<DocumentSigningState> {
  return getRuntimeAdapter().invoke<DocumentSigningState>(
    'document.freeze',
    { caseId, actorId: currentOperatorId() },
    { timeoutMs: 90_000 },
  )
}

export function finalizeDocument(caseId: string): Promise<DocumentSigningState> {
  return getRuntimeAdapter().invoke<DocumentSigningState>(
    'document.finalize',
    { caseId, actorId: currentOperatorId() },
    { timeoutMs: 90_000 },
  )
}

export function signDocument(
  caseId: string,
  signerRole: DocumentSignerRole,
  signerName: string,
  imageDataUrl: string,
  strokesJson: string,
): Promise<DocumentSigningState> {
  return getRuntimeAdapter().invoke<DocumentSigningState>('document.sign', {
    caseId,
    signerRole,
    signerName,
    imageDataUrl,
    strokesJson,
    actorId: currentOperatorId(),
  }, { timeoutMs: 60_000 })
}
