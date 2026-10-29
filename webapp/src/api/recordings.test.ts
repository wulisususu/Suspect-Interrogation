import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const patch = vi.fn()

vi.mock('./http', () => ({ http: { get, post: vi.fn(), patch, delete: vi.fn() } }))

const envelope = (data: unknown) => ({ data: { ok: true, code: 'OK', message: 'OK', data } })

const recordings = {
  caseId: 'CASE 1',
  fullRecordingEnabled: true,
  questions: [],
  originals: [],
  originalAccessRequiresAdmin: true,
}

describe('recording client', () => {
  beforeEach(() => {
    get.mockReset()
    patch.mockReset()
  })

  it('reads a case recording listing with an encoded case id', async () => {
    get.mockResolvedValue(envelope(recordings))
    const { fetchCaseRecordings } = await import('./recordings')
    const result = await fetchCaseRecordings('CASE 1')
    expect(get).toHaveBeenCalledWith('/api/v1/cases/CASE%201/recordings')
    expect(result.originalAccessRequiresAdmin).toBe(true)
  })

  it('patches the full-recording switch with the aliased body', async () => {
    patch.mockResolvedValue(envelope({ caseId: 'CASE1', fullRecordingEnabled: false }))
    const { updateRecordingOptions } = await import('./recordings')
    await updateRecordingOptions('CASE1', false)
    expect(patch).toHaveBeenCalledWith('/api/v1/cases/CASE1/recording-options', { fullRecordingEnabled: false })
  })

  it('builds question audio urls with and without a fragment', async () => {
    const { questionAudioUrl } = await import('./recordings')
    const base = { questionId: 'q1', captureSessionId: 'c1', fragmentId: null, audioUrl: 'x' }
    expect(questionAudioUrl(recordings, { ...base, available: true } as never))
      .toBe('/api/v1/cases/CASE%201/recordings/questions/q1/captures/c1/audio')
    expect(questionAudioUrl(recordings, { ...base, fragmentId: 'f1', available: true } as never))
      .toBe('/api/v1/cases/CASE%201/recordings/questions/q1/captures/c1/fragments/f1/audio')
    expect(questionAudioUrl(recordings, { ...base, audioUrl: null, available: false } as never)).toBeNull()
  })

  it('requires a reason in the original-audio url and encodes it', async () => {
    const { originalAudioUrl } = await import('./recordings')
    expect(originalAudioUrl('CASE1', 'c9', '核对 录音/时间'))
      .toBe('/api/v1/cases/CASE1/recordings/originals/c9/audio?reason=%E6%A0%B8%E5%AF%B9%20%E5%BD%95%E9%9F%B3%2F%E6%97%B6%E9%97%B4')
  })
})
