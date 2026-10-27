import type { AxiosRequestConfig } from 'axios'
import { http } from '../api/http'
import { RuntimeAdapterError } from './errors'
import { capability, capabilitySet, type RuntimeAdapter, type RuntimeCapabilities, type RuntimeEventListener, type RuntimeInvokeOptions, type RuntimeOperation, type RuntimeSessionConnection } from './types'

function encode(value: unknown) { return encodeURIComponent(String(value ?? '')) }

function unavailable(operation: string): never {
  const model = operation.startsWith('llm.') || operation.startsWith('ocr.') || operation.startsWith('asr.') || operation.startsWith('ai.') || operation.startsWith('model.') || operation.startsWith('case.ai.')
  throw new RuntimeAdapterError(
    model ? 'MODEL_NOT_INSTALLED' : 'CAPABILITY_NOT_CONFIGURED',
    model ? '浏览器开发模式未配置本地模型 Runtime' : '浏览器开发模式未配置该设备能力',
    model ? 'MODEL_NOT_INSTALLED' : 'NOT_CONFIGURED',
  )
}

function browserVoiceRoleDraft(caseId: string) {
  const fallback = { caseId, interrogatorOfficerId: null, recorderOfficerId: null }
  if (typeof localStorage === 'undefined') return fallback
  try {
    const stored = localStorage.getItem(`suspect-interrogation:voice-role-draft:${caseId}`)
    if (!stored) return fallback
    const parsed = JSON.parse(stored) as Record<string, unknown>
    return {
      caseId,
      interrogatorOfficerId: parsed.interrogatorOfficerId == null ? null : String(parsed.interrogatorOfficerId),
      recorderOfficerId: parsed.recorderOfficerId == null ? null : String(parsed.recorderOfficerId),
    }
  } catch {
    return fallback
  }
}

function voiceprintMock<T>(operation: string, payload: Record<string, unknown>): T | undefined {
  const simulated = true
  switch (operation) {
    case 'voiceprint.readiness':
      return {
        suspectReady: false,
        interrogatorReady: false,
        recorderReady: false,
        recognitionMode: 'SUSPECT_ONLY',
        canStart: false,
        roleBindingScope: 'NONE',
        roleBindingSessionId: null,
        simulated,
      } as T
    case 'voiceprint.roleDraft.get':
      return browserVoiceRoleDraft(String(payload.caseId ?? '')) as T
    case 'voiceprint.roleDraft.update': {
      const draft = {
        caseId: String(payload.caseId ?? ''),
        interrogatorOfficerId: payload.interrogatorOfficerId == null ? null : String(payload.interrogatorOfficerId),
        recorderOfficerId: payload.recorderOfficerId == null ? null : String(payload.recorderOfficerId),
      }
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(`suspect-interrogation:voice-role-draft:${draft.caseId}`, JSON.stringify(draft))
      }
      return draft as T
    }
    case 'voiceprint.enrollment.status':
      return { active: false, capturedDurationMs: 0, targetDurationMs: 30000, complete: false, simulated } as T
    case 'voiceprint.suspect.enrollment.start':
      return { state: 'RECORDING', caseId: String(payload.caseId ?? ''), ready: false, simulated } as T
    case 'voiceprint.suspect.enrollment.stop':
      return { state: 'SIMULATED', caseId: String(payload.caseId ?? ''), ready: false, simulated } as T
    case 'officerVoiceprint.list':
      return [] as T
    case 'officerVoiceprint.enrollment.start':
      return {
        state: 'RECORDING',
        officerId: String(payload.officerId ?? ''),
        officerName: String(payload.officerName ?? ''),
        active: false,
        simulated,
      } as T
    case 'officerVoiceprint.enrollment.stop':
      return {
        state: 'SIMULATED',
        officerId: String(payload.officerId ?? ''),
        active: false,
        simulated,
      } as T
    case 'officerVoiceprint.revoke':
      return {
        officerId: String(payload.officerId ?? ''),
        officerName: '浏览器模拟民警',
        active: false,
        modelId: 'browser-dev-simulated',
        modelVersion: null,
        quality: 'SIMULATED',
        usableDurationMs: 0,
        simulated,
      } as T
    case 'voiceprint.assignments.update':
      return {
        suspectReady: false,
        interrogatorReady: false,
        recorderReady: false,
        recognitionMode: 'SUSPECT_ONLY',
        canStart: false,
        roleBindingScope: 'NONE',
        roleBindingSessionId: null,
        simulated,
      } as T
    default:
      return undefined
  }
}

function legacyConfig(operation: string, payload: Record<string, unknown>): AxiosRequestConfig | undefined {
  const caseId = encode(payload.caseId)
  const messageId = encode(payload.messageId)
  switch (operation) {
    case 'case.create': return { method: 'POST', url: '/api/cases/create', data: payload }
    case 'case.intake': return { method: 'POST', url: '/api/v1/cases/intake', data: payload }
    case 'case.list': return { method: 'GET', url: '/api/cases', params: { limit: payload.limit } }
    case 'case.get': return { method: 'GET', url: `/api/cases/${caseId}` }
    case 'case.update': return { method: 'PUT', url: `/api/cases/${caseId}`, data: payload.patch ?? payload }
    case 'message.list': return { method: 'GET', url: `/api/cases/${caseId}/messages`, params: { limit: payload.limit ?? 1000 } }
    case 'message.add': return { method: 'POST', url: `/work/case/${caseId}/message`, data: { profile: { text: payload.text, from: payload.speaker } } }
    case 'message.update': return { method: 'PUT', url: `/api/cases/${caseId}/messages/${messageId}`, data: { text: payload.text, reason: payload.reason } }
    case 'message.mark': return { method: 'POST', url: `/api/cases/${caseId}/messages/${messageId}/mark`, data: { mark: payload.mark } }
    case 'message.revisions': {
      const suffix = payload.messageId ? `/messages/${messageId}/revisions` : '/revisions'
      return { method: 'GET', url: `/api/cases/${caseId}${suffix}` }
    }
    case 'fact.list': return { method: 'GET', url: `/api/cases/${caseId}/facts` }
    case 'fact.update': return { method: 'PUT', url: `/api/cases/${caseId}/facts/${encode(payload.factKey)}`, data: payload.patch ?? payload }
    // 后端没有 timeline 路由；此处不再伪装成可用接口（与 Linux 适配器保持一致）。
    case 'session.get': return { method: 'GET', url: `/api/cases/${caseId}/session` }
    case 'session.start': return {
      method: 'POST',
      url: `/api/cases/${caseId}/session/start`,
      data: {
        interrogator_officer_id: payload.interrogatorOfficerId ?? null,
        recorder_officer_id: payload.recorderOfficerId ?? null,
        actor_id: payload.actorId,
      },
    }
    case 'session.pause': return { method: 'POST', url: `/api/cases/${caseId}/session/pause` }
    case 'session.resume': return { method: 'POST', url: `/api/cases/${caseId}/session/resume` }
    case 'session.finish': return { method: 'POST', url: `/api/cases/${caseId}/session/finish` }
    case 'session.stage': return { method: 'POST', url: `/api/cases/${caseId}/session/stage`, data: { stage: payload.stage } }
    case 'device.action': return { method: 'POST', url: '/api/device/action', data: { type: payload.type } }
    default: return undefined
  }
}

export class BrowserDevAdapter implements RuntimeAdapter {
  readonly kind = 'browser-dev' as const

  async invoke<T>(operation: RuntimeOperation, payload: Record<string, unknown> = {}, options: RuntimeInvokeOptions = {}): Promise<T> {
    const simulated = voiceprintMock<T>(operation, payload)
    if (simulated !== undefined) return simulated
    const config = legacyConfig(operation, payload)
    if (!config) return unavailable(operation)
    const response = await http.request<T>({ ...config, ...(options.timeoutMs ? { timeout: options.timeoutMs } : {}) })
    const body = response.data as unknown
    if (body && typeof body === 'object' && 'ok' in body && 'data' in body) {
      const envelope = body as { ok: boolean; data: T; code?: string; message?: string }
      if (!envelope.ok) throw new RuntimeAdapterError(envelope.code || 'BACKEND_ERROR', envelope.message || '浏览器开发后端返回错误')
      return envelope.data
    }
    return response.data
  }

  async getCapabilities(): Promise<RuntimeCapabilities> {
    const result = capabilitySet('NOT_CONFIGURED', '浏览器开发模式未连接硬件')
    result.asr = capability('asr', 'MODEL_NOT_INSTALLED', '浏览器开发模式未加载 ASR 模型')
    result.ocr = capability('ocr', 'MODEL_NOT_INSTALLED', '浏览器开发模式未加载 OCR 模型')
    result.llm = capability('llm', 'MODEL_NOT_INSTALLED', '浏览器开发模式未加载 LLM 模型')
    result.recording = capability('recording', 'MODEL_NOT_INSTALLED', '浏览器开发模式未加载连续 ASR Runtime')
    return result
  }

  connectSession(_sessionId: string, _listener: RuntimeEventListener): RuntimeSessionConnection {
    return { close() {}, send() { return false } }
  }
}
