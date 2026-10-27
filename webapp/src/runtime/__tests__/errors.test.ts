import { describe, expect, it } from 'vitest'
import { normalizeRuntimeError, RuntimeAdapterError } from '../errors'

function httpError(status: number, data?: unknown) {
  return { response: { status, data } }
}

describe('normalizeRuntimeError', () => {
  it('keeps a domain 404 message instead of blaming the local model', () => {
    const normalized = normalizeRuntimeError(
      httpError(404, { ok: false, code: 'ASR_FRAGMENT_NOT_FOUND', message: 'ASR 临时片段不存在' }),
      'asr.fragment.update',
    )

    expect(normalized.code).toBe('ASR_FRAGMENT_NOT_FOUND')
    expect(normalized.message).toBe('ASR 临时片段不存在')
    expect(normalized.state).toBe('ERROR')
    expect(normalized.capability).toBe('asr')
  })

  it('still reports a missing model when the route itself is absent', () => {
    const normalized = normalizeRuntimeError(
      httpError(404, { ok: false, code: 'NOT_FOUND', message: '接口不存在' }),
      'asr.capture.start',
    )

    expect(normalized.code).toBe('MODEL_NOT_INSTALLED')
    expect(normalized.state).toBe('MODEL_NOT_INSTALLED')
  })

  it('treats a bare 404 without a backend envelope as a missing capability', () => {
    const normalized = normalizeRuntimeError(httpError(404), 'ocr.recognize')

    expect(normalized.code).toBe('MODEL_NOT_INSTALLED')
    expect(normalized.message).toContain('本地模型')
  })

  it('does not blame a model for unrelated resources missing on a non-model route', () => {
    const normalized = normalizeRuntimeError(
      httpError(404, { ok: false, code: 'CASE_NOT_FOUND', message: '案件不存在' }),
      'case.get',
    )

    expect(normalized.code).toBe('CASE_NOT_FOUND')
    expect(normalized.message).toBe('案件不存在')
    expect(normalized.state).toBe('ERROR')
  })

  it('keeps explicit capability codes from the backend', () => {
    const normalized = normalizeRuntimeError(
      httpError(503, { ok: false, code: 'MODEL_NOT_INSTALLED', message: '声纹模型未安装' }),
      'asr.capture.start',
    )

    expect(normalized.code).toBe('MODEL_NOT_INSTALLED')
    expect(normalized.message).toBe('声纹模型未安装')
  })

  it('returns the original adapter error unchanged', () => {
    const original = new RuntimeAdapterError('BUSY', '正在录音', 'BUSY', 'recording')
    expect(normalizeRuntimeError(original, 'asr.capture.start')).toBe(original)
  })
})
