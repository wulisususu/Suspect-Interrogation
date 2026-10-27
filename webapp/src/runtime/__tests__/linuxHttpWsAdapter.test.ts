import { describe, expect, it } from 'vitest'
import { LinuxHttpWsAdapter, buildRuntimeWebSocketUrl } from '../linuxHttpWsAdapter'
import { RuntimeAdapterError } from '../errors'

describe('LinuxHttpWsAdapter', () => {
  it('passes a case-list query to FastAPI', async () => {
    const calls: Array<{ params?: Record<string, unknown> }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ params: config.params })
        return { data: { ok: true, data: [] } }
      },
    })

    await adapter.invoke('case.list', { limit: 100, query: '3201011' })
    expect(calls[0].params).toEqual({ limit: 100, query: '3201011' })
  })

  it('omits an empty case-list query so FastAPI can use its default listing', async () => {
    const calls: Array<{ params?: Record<string, unknown> }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ params: config.params })
        return { data: { ok: true, data: [] } }
      },
    })

    await adapter.invoke('case.list', { limit: 50, query: '' })
    expect(calls[0].params).toEqual({ limit: 50 })
  })

  it('requests superseded transcript fragments when loading lineage history', async () => {
    const calls: Array<{ method?: unknown; url?: unknown; params?: Record<string, unknown> }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: config.method, url: config.url, params: config.params })
        return { data: { ok: true, data: [] } }
      },
    })

    await adapter.invoke('asr.fragment.list', {
      caseId: 'CASE-001',
      includeConfirmed: true,
      includeSuperseded: true,
    })

    expect(calls).toEqual([{
      method: 'GET',
      url: '/api/v1/cases/CASE-001/asr/fragments',
      params: { include_confirmed: true, include_superseded: true },
    }])
  })

  it('maps atomic case intake to the canonical endpoint', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { ok: true, data: { id: 'CASE-001' } } }
      },
    })
    const intake = {
      operatorId: 'officer-01',
      officerName: '李警官',
      identity: { name: '赵某', idNumber: '320101199001010011', source: 'MANUAL' },
    }

    await adapter.invoke('case.intake', intake)

    expect(calls).toEqual([{ method: 'POST', url: '/api/v1/cases/intake', data: intake }])
  })

  it('sends manual transcript speakers using the formal FastAPI field name', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { ok: true, data: {} } }
      },
    })

    await adapter.invoke('message.add', { caseId: 'CASE-001', text: '请说明情况。', speaker: '民警' })

    expect(calls).toEqual([{
      method: 'POST',
      url: '/api/v1/cases/CASE-001/messages',
      data: { text: '请说明情况。', speaker: '民警' },
    }])
  })

  it('routes Linux operations through /api/v1 and preserves identity case binding', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { status: 'pending' } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('identity.read', { caseId: 'CASE-001', actorId: 'officer-01' })
    expect(calls[0]).toMatchObject({
      method: 'POST',
      url: '/api/v1/identity/read',
      data: { case_id: 'CASE-001', actor_id: 'officer-01' },
    })
  })

  it('maps reviewed identity fields to the canonical confirmation endpoint', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { name: '赵某', caseId: 'CASE-001' } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('identity.confirm', {
      caseId: 'CASE-001',
      actorId: 'officer-01',
      name: '赵某',
      idNumber: '320101199001010011',
      gender: '男',
      nation: '汉',
      birthDate: '1990-01-01',
      address: '测试地址',
      source: 'MANUAL',
    })

    expect(calls[0]).toMatchObject({
      method: 'POST',
      url: '/api/v1/identity/confirm',
      data: {
        case_id: 'CASE-001',
        actor_id: 'officer-01',
        name: '赵某',
        id_number: '320101199001010011',
        gender: '男',
        nation: '汉',
        birth_date: '1990-01-01',
        address: '测试地址',
        source: 'MANUAL',
      },
    })
  })

  it('uses the canonical case session endpoints exposed by FastAPI', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { status: 'RUNNING', case_id: 'CASE-001', stage: 'IDENTITY' } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('session.start', {
      caseId: 'CASE-001',
      interrogatorOfficerId: 'POL-1',
      recorderOfficerId: null,
      actorId: 'actor-1',
    })
    await adapter.invoke('session.pause', { caseId: 'CASE-001' })
    await adapter.invoke('session.resume', { caseId: 'CASE-001' })
    await adapter.invoke('session.stage', { caseId: 'CASE-001', stage: 'STATEMENT' })
    await adapter.invoke('session.finish', { caseId: 'CASE-001' })

    expect(calls).toEqual([
      {
        method: 'POST',
        url: '/api/v1/cases/CASE-001/session/start',
        data: { interrogator_officer_id: 'POL-1', recorder_officer_id: null, actor_id: 'actor-1' },
      },
      { method: 'POST', url: '/api/v1/cases/CASE-001/session/pause', data: {} },
      { method: 'POST', url: '/api/v1/cases/CASE-001/session/resume', data: {} },
      { method: 'POST', url: '/api/v1/cases/CASE-001/session/stage', data: { stage: 'STATEMENT' } },
      { method: 'POST', url: '/api/v1/cases/CASE-001/session/finish', data: {} },
    ])
  })

  it('maps voiceprint operations to canonical Linux endpoints and payloads', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown; params?: Record<string, unknown> }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({
          method: String(config.method),
          url: String(config.url),
          data: config.data,
          params: config.params,
        })
        return { data: { ok: true, data: {} } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('voiceprint.readiness', { caseId: 'CASE-001' })
    await adapter.invoke('voiceprint.suspect.enrollment.start', { caseId: 'CASE-001', actorId: 'actor-1' })
    await adapter.invoke('voiceprint.suspect.enrollment.stop', { caseId: 'CASE-001', actorId: 'actor-1' })
    await adapter.invoke('officerVoiceprint.list', { activeOnly: false })
    await adapter.invoke('officerVoiceprint.enrollment.start', { officerId: 'POL-1', officerName: '李警官', actorId: 'actor-1' })
    await adapter.invoke('officerVoiceprint.enrollment.stop', { officerId: 'POL-1', actorId: 'actor-1' })
    await adapter.invoke('officerVoiceprint.revoke', { officerId: 'POL-1', actorId: 'actor-1' })
    await adapter.invoke('voiceprint.assignments.update', {
      caseId: 'CASE-001',
      interrogatorOfficerId: 'POL-1',
      recorderOfficerId: 'POL-2',
      actorId: 'actor-1',
    })

    expect(calls).toEqual([
      { method: 'GET', url: '/api/v1/cases/CASE-001/voiceprints/readiness', data: undefined, params: undefined },
      { method: 'POST', url: '/api/v1/cases/CASE-001/voiceprints/suspect/enrollment/start', data: { actor_id: 'actor-1' }, params: undefined },
      { method: 'POST', url: '/api/v1/cases/CASE-001/voiceprints/suspect/enrollment/stop', data: { actor_id: 'actor-1' }, params: undefined },
      { method: 'GET', url: '/api/v1/officer-voiceprints', data: undefined, params: { active_only: false } },
      { method: 'POST', url: '/api/v1/officer-voiceprints/POL-1/enrollment/start', data: { officer_name: '李警官', actor_id: 'actor-1' }, params: undefined },
      { method: 'POST', url: '/api/v1/officer-voiceprints/POL-1/enrollment/stop', data: { actor_id: 'actor-1' }, params: undefined },
      { method: 'DELETE', url: '/api/v1/officer-voiceprints/POL-1', data: undefined, params: { actor_id: 'actor-1' } },
      {
        method: 'PUT',
        url: '/api/v1/cases/CASE-001/voiceprints/assignments',
        data: { interrogator_officer_id: 'POL-1', recorder_officer_id: 'POL-2', actor_id: 'actor-1' },
        params: undefined,
      },
    ])
  })

  it('finalizes an interrogation through the single backend command', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { ok: true, data: {} } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('document.finalize', { caseId: 'CASE-001' })

    expect(calls).toEqual([
      { method: 'POST', url: '/api/v1/cases/CASE-001/document/finalize', data: {} },
    ])
  })

  it('signs a document with only the fields the strict backend accepts', async () => {
    const calls: Array<{ method: string; url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ method: String(config.method), url: String(config.url), data: config.data })
        return { data: { ok: true, data: {} } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('document.sign', {
      caseId: 'CASE-001',
      signerRole: 'SUSPECT',
      signerName: '张三',
      imageDataUrl: 'data:image/png;base64,AAAA',
      strokesJson: '[]',
    })

    expect(calls).toEqual([
      {
        method: 'POST',
        url: '/api/v1/cases/CASE-001/document/sign',
        data: {
          signerRole: 'SUSPECT',
          signerName: '张三',
          imageDataUrl: 'data:image/png;base64,AAAA',
          strokesJson: '[]',
        },
      },
    ])
    // 后端 DocumentSignRequest 是 extra="forbid"，caseId 只允许出现在 URL 里。
    expect(calls[0]!.data).not.toHaveProperty('caseId')
  })

  it('forwards the signer actor id when the caller supplies one', async () => {
    const calls: Array<{ data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ data: config.data })
        return { data: { ok: true, data: {} } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('document.sign', {
      caseId: 'CASE-001',
      signerRole: 'OFFICER',
      signerName: '李四',
      imageDataUrl: 'data:image/png;base64,BBBB',
      strokesJson: '[]',
      actorId: 'OFFICER-9',
    })

    expect(calls[0]!.data).toEqual({
      signerRole: 'OFFICER',
      signerName: '李四',
      imageDataUrl: 'data:image/png;base64,BBBB',
      strokesJson: '[]',
      actorId: 'OFFICER-9',
    })
  })

  it('carries the operator id into session changes so the audit trail keeps a person', async () => {
    const calls: Array<{ url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ url: String(config.url), data: config.data })
        return { data: { ok: true, data: {} } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('session.pause', { caseId: 'CASE-002', actorId: 'OFFICER-3' })
    await adapter.invoke('session.finish', { caseId: 'CASE-002' })
    await adapter.invoke('document.freeze', { caseId: 'CASE-002', actorId: 'OFFICER-3' })
    await adapter.invoke('case.report.generated', { caseId: 'CASE-002', actorId: 'OFFICER-3' })

    expect(calls).toEqual([
      { url: '/api/v1/cases/CASE-002/session/pause', data: { actor_id: 'OFFICER-3' } },
      { url: '/api/v1/cases/CASE-002/session/finish', data: {} },
      { url: '/api/v1/cases/CASE-002/document/freeze', data: { actor_id: 'OFFICER-3' } },
      { url: '/api/v1/cases/CASE-002/report/generated', data: { actor_id: 'OFFICER-3' } },
    ])
  })

  it('sends applied fragments with the backend field name instead of relying on the empty-list fallback', async () => {
    const calls: Array<{ url: string; data?: unknown }> = []
    const adapter = new LinuxHttpWsAdapter({
      request: async (config) => {
        calls.push({ url: String(config.url), data: config.data })
        return { data: { ok: true, data: { confirmedCount: 1, fragments: [] } } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    await adapter.invoke('asr.fragment.applyToRecord', {
      caseId: 'CASE-003',
      fragmentIds: ['frag-1', 'frag-2'],
      actorId: 'OFFICER-3',
    })

    // 后端 FragmentBatchRequest 收 fragment_ids；传 fragmentIds 会被当成空列表，
    // 进而退化为"把该案所有待确认片段一次性写入笔录"。
    expect(calls).toEqual([{
      url: '/api/v1/cases/CASE-003/asr/fragments/apply',
      data: { fragment_ids: ['frag-1', 'frag-2'], actor_id: 'OFFICER-3' },
    }])
  })

  it('rejects the timeline operation because the backend has no such route', async () => {
    const adapter = new LinuxHttpWsAdapter({
      request: async () => ({ data: { ok: true, data: [] } }),
      origin: 'http://127.0.0.1:8080',
    })

    await expect(adapter.invoke('timeline.list', { caseId: 'CASE-003' })).rejects.toMatchObject<Partial<RuntimeAdapterError>>({
      code: 'UNSUPPORTED_OPERATION',
      state: 'NOT_CONFIGURED',
    })
  })

  it('rejects retired operations that have no formal Linux FastAPI route', async () => {
    const adapter = new LinuxHttpWsAdapter({
      request: async () => ({ data: { ok: true, data: {} } }),
    })

    for (const operation of [
      'case.ai.list',
      'model.list',
      'llm.status',
      'asr.status',
      'ocr.status',
      'ai.inquiry',
      'report.get',
    ]) {
      await expect(adapter.invoke(operation)).rejects.toMatchObject<Partial<RuntimeAdapterError>>({
        code: 'UNSUPPORTED_OPERATION',
        state: 'NOT_CONFIGURED',
      })
    }
  })

  it('normalizes network failures to NOT_CONNECTED', async () => {
    const adapter = new LinuxHttpWsAdapter({
      request: async () => { throw Object.assign(new Error('offline'), { code: 'ERR_NETWORK' }) },
      origin: 'http://127.0.0.1:8080',
    })

    await expect(adapter.invoke('identity.read')).rejects.toMatchObject<Partial<RuntimeAdapterError>>({
      code: 'BACKEND_OFFLINE',
      state: 'NOT_CONNECTED',
    })
  })

  it('returns explicit not-ready capability states when the capability endpoint is absent', async () => {
    const adapter = new LinuxHttpWsAdapter({
      request: async () => {
        throw { response: { status: 404, data: { code: 'NOT_FOUND' } } }
      },
      origin: 'http://127.0.0.1:8080',
    })

    const capabilities = await adapter.getCapabilities()
    expect(capabilities.ocr.state).toBe('MODEL_NOT_INSTALLED')
    expect(capabilities.llm.state).toBe('MODEL_NOT_INSTALLED')
    expect(capabilities.identity.state).toBe('NOT_CONFIGURED')
  })

  it('derives ws/wss URLs from the local browser origin', () => {
    expect(buildRuntimeWebSocketUrl('http://127.0.0.1:8080', 'abc def')).toBe('ws://127.0.0.1:8080/ws/interrogation/abc%20def')
    expect(buildRuntimeWebSocketUrl('https://kiosk.local/', 'session-1')).toBe('wss://kiosk.local/ws/interrogation/session-1')
  })
})
