import { afterEach, describe, expect, it, vi } from 'vitest'
import { http } from './http'
import { fetchSelfServiceState, recordSelfServiceEvent } from './selfService'

afterEach(() => vi.restoreAllMocks())

describe('self-service api', () => {
  it('reads the confirmation state and records events with the question id only when given', async () => {
    const state = { caseId: 'c1', identityConfirmedAt: null, handedOverAt: null, confirmedAnswers: [] }
    const get = vi.spyOn(http, 'get').mockResolvedValue({ data: { ok: true, data: state } })
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: { ok: true, data: state } })
    expect(await fetchSelfServiceState('c1')).toEqual(state)
    expect(get).toHaveBeenCalledWith('/api/v1/cases/c1/self-service')
    await recordSelfServiceEvent('c1', 'IDENTITY_CONFIRM')
    await recordSelfServiceEvent('c1', 'ANSWER_CONFIRM', 'q3')
    expect(post.mock.calls).toEqual([
      ['/api/v1/cases/c1/self-service/events', { kind: 'IDENTITY_CONFIRM' }],
      ['/api/v1/cases/c1/self-service/events', { kind: 'ANSWER_CONFIRM', questionId: 'q3' }],
    ])
    await recordSelfServiceEvent('c1', 'EXIT', undefined, { reason: '设备故障', step: 'answer' })
    expect(post.mock.calls.at(-1)).toEqual(['/api/v1/cases/c1/self-service/events', { kind: 'EXIT', reason: '设备故障', step: 'answer' }])
  })

  it('surfaces backend refusals', async () => {
    vi.spyOn(http, 'post').mockResolvedValue({ data: { ok: false, code: 'SELF_SERVICE_NO_ANSWER', message: '本题还没有回答，不能确认' } })
    await expect(recordSelfServiceEvent('c1', 'ANSWER_CONFIRM', 'q1')).rejects.toThrow('本题还没有回答')
  })
})
