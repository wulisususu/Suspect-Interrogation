import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { currentOperatorId, resetCurrentOperator } from '../api/operator'
import { capabilitySet, type RuntimeCapabilities } from '../runtime/types'
import type { CaseSummary, SessionState } from '../types/interrogation'

const fetchCaseOfficers = vi.fn()
const fetchVoiceprintReadiness = vi.fn()
const fetchOfficerVoiceprints = vi.fn()
const fetchVoiceprintRoleDraft = vi.fn()

const availableCapabilities = (): RuntimeCapabilities => {
  const capabilities = capabilitySet('AVAILABLE')
  capabilities.recording = { ...capabilities.recording, state: 'AVAILABLE' }
  capabilities.asr = { ...capabilities.asr, state: 'AVAILABLE' }
  return capabilities
}

const summaryFor = (caseId: string): CaseSummary => ({
  id: caseId,
  suspectName: '测试',
  officerName: '张伟',
  state: 'IDENTITY_READY',
  workflowState: 'IDENTITY_READY',
  stage: 'IDENTITY',
})

const sessionFor = (caseId: string): SessionState => ({
  id: 'session-1',
  caseId,
  status: 'READY',
  stage: 'IDENTITY',
  startedAt: null,
  pausedAt: null,
  endedAt: null,
  updatedAt: 0,
})

vi.mock('../api/interrogation', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/interrogation')>()
  return {
    ...actual,
    fetchCase: async (caseId: string) => summaryFor(caseId),
    fetchRuntimeCapabilities: async () => availableCapabilities(),
    fetchMessages: async () => [],
    fetchFacts: async () => [],
    fetchSessionState: async (caseId: string) => sessionFor(caseId),
    fetchAsrCaptureStatus: async () => null,
    fetchCaseOfficers: (...args: unknown[]) => fetchCaseOfficers(...args),
    fetchVoiceprintReadiness: (...args: unknown[]) => fetchVoiceprintReadiness(...args),
    fetchOfficerVoiceprints: (...args: unknown[]) => fetchOfficerVoiceprints(...args),
    fetchVoiceprintRoleDraft: (...args: unknown[]) => fetchVoiceprintRoleDraft(...args),
    connectRuntimeSession: () => ({ close: () => undefined, send: () => true }),
  }
})

describe('case load no longer depends on the voiceprint library', () => {
  beforeEach(() => {
    vi.stubGlobal('location', { search: '' })
    setActivePinia(createPinia())
    fetchCaseOfficers.mockReset()
    fetchVoiceprintReadiness.mockReset()
    fetchOfficerVoiceprints.mockReset()
    fetchVoiceprintRoleDraft.mockReset()
    resetCurrentOperator()
  })

  afterEach(() => {
    resetCurrentOperator()
  })

  it('reads the case officer binding and never calls the voiceprint endpoints', async () => {
    fetchCaseOfficers.mockResolvedValue({
      interrogator: { officerId: '038291', officerName: '张伟', unit: '紫琅湖派出所' },
      recorder: { officerId: '036612', officerName: '刘敏', unit: '紫琅湖派出所' },
    })
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')

    await store.initialize()

    expect(fetchCaseOfficers).toHaveBeenCalledWith('case-1')
    expect(fetchVoiceprintReadiness).not.toHaveBeenCalled()
    expect(fetchOfficerVoiceprints).not.toHaveBeenCalled()
    expect(fetchVoiceprintRoleDraft).not.toHaveBeenCalled()
    expect(store.caseOfficers.map((officer) => officer.officerId)).toEqual(['038291', '036612'])
    expect(store.selectedInterrogatorOfficerId).toBe('038291')
    expect(store.selectedRecorderOfficerId).toBe('036612')
    expect(currentOperatorId()).toBe('038291')
  })

  it('leaves the audit operator empty when the case has no bound officer', async () => {
    fetchCaseOfficers.mockResolvedValue({ interrogator: null, recorder: null })
    const { useInterrogationStore } = await import('./interrogation')
    const store = useInterrogationStore()
    store.resetCaseContext('case-1')

    await store.initialize()

    expect(store.caseOfficers).toEqual([])
    expect(store.selectedInterrogatorOfficerId).toBeNull()
    expect(currentOperatorId()).toBeUndefined()
  })
})
