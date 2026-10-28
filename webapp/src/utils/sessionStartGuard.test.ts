import { describe, expect, it } from 'vitest'
import { capabilitySet, capability } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'
import { sessionStartGuard } from './sessionStartGuard'

const summary = (patch: Partial<CaseSummary> = {}) => ({ id: 'C-1', suspectName: '王某某', idNumber: '330501199205142319', identitySource: 'MANUAL', ...patch }) as CaseSummary
const ready = { ...capabilitySet('NOT_CONFIGURED'), microphone: capability('microphone', 'AVAILABLE'), asr: capability('asr', 'AVAILABLE') }

describe('sessionStartGuard', () => {
  it('unlocks with identity and devices alone, no voiceprint involved', () => {
    expect(sessionStartGuard(summary(), ready)).toMatchObject({ disabled: false, missing: [] })
  })

  it('lists missing identity and device checks', () => {
    const guard = sessionStartGuard(summary({ idNumber: '' }), null)
    expect(guard.disabled).toBe(true)
    expect(guard.missing).toEqual(['身份信息', '设备自检'])
    expect(guard.reason).toBe('完成以下项目后解锁：身份信息、设备自检')
  })
})
