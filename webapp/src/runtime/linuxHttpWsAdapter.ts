import type { AxiosRequestConfig } from 'axios'
import { http } from '../api/http'
import {
  BrowserFormalCaptureLeaseError,
  confirmBrowserAsrCaptureFinalized,
  startBrowserAsrCapture,
  stopBrowserAsrCapture,
} from '../audio/browserAsrCapture'
import { audioInputMode } from '../config/audioInput'
import { runtimeConfig } from '../config/runtime'
import { normalizeRuntimeError, RuntimeAdapterError } from './errors'
import {
  capability,
  capabilitySet,
  type RuntimeAdapter,
  type RuntimeCapabilities,
  type RuntimeCapabilityName,
  type RuntimeCapabilityState,
  type RuntimeEventListener,
  type RuntimeInvokeOptions,
  type RuntimeOperation,
  type RuntimeSessionConnection,
} from './types'
import { RuntimeWebSocketClient, type RuntimeWebSocketConstructor } from './wsClient'

export interface RuntimeHttpRequestConfig {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  url: string
  data?: unknown
  params?: Record<string, unknown>
  timeout?: number
}

export type RuntimeHttpRequest = <T = unknown>(config: RuntimeHttpRequestConfig) => Promise<{ data: T }>

interface LinuxAdapterOptions {
  request?: RuntimeHttpRequest
  origin?: string
  WebSocketCtor?: RuntimeWebSocketConstructor
}

function encode(value: unknown) {
  return encodeURIComponent(String(value ?? ''))
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'ok' in payload && 'data' in payload) {
    const envelope = payload as { ok: boolean; data: T; code?: string; message?: string }
    if (!envelope.ok) throw new RuntimeAdapterError(envelope.code || 'BACKEND_ERROR', envelope.message || 'Linux 后端返回错误')
    return envelope.data
  }
  return payload as T
}

/** ActorRequest 用 snake_case 字段名且没有 alias，只透传真实存在的操作人。 */
function actorBody(payload: Record<string, unknown>): Record<string, unknown> {
  return payload.actorId === undefined ? {} : { actor_id: payload.actorId }
}

function endpoint(operation: RuntimeOperation, payload: Record<string, unknown>): RuntimeHttpRequestConfig {
  const caseId = encode(payload.caseId)
  const messageId = encode(payload.messageId)
  const fragmentId = encode(payload.fragmentId)
  const officerId = encode(payload.officerId)

  switch (operation) {
    case 'case.create': return { method: 'POST', url: '/api/v1/cases', data: payload }
    case 'case.intake': return { method: 'POST', url: '/api/v1/cases/intake', data: payload }
    case 'case.list': {
      const params: Record<string, unknown> = { limit: payload.limit }
      if (typeof payload.query === 'string' && payload.query) params.query = payload.query
      return { method: 'GET', url: '/api/v1/cases', params }
    }
    case 'case.get': return { method: 'GET', url: `/api/v1/cases/${caseId}` }
    case 'case.update': return { method: 'PUT', url: `/api/v1/cases/${caseId}`, data: { ...(payload.patch ?? {} as Record<string, unknown>), ...actorBody(payload) } }
    case 'message.list': return { method: 'GET', url: `/api/v1/cases/${caseId}/messages`, params: { limit: payload.limit ?? 1000 } }
    case 'message.add': return { method: 'POST', url: `/api/v1/cases/${caseId}/messages`, data: { text: payload.text, speaker: payload.speaker, ...actorBody(payload) } }
    case 'message.update': return { method: 'PUT', url: `/api/v1/cases/${caseId}/messages/${messageId}`, data: { text: payload.text, reason: payload.reason, ...actorBody(payload) } }
    case 'message.mark': return { method: 'POST', url: `/api/v1/cases/${caseId}/messages/${messageId}/mark`, data: { mark: payload.mark, ...actorBody(payload) } }
    case 'message.revisions': {
      const suffix = payload.messageId ? `/messages/${messageId}/revisions` : '/revisions'
      return { method: 'GET', url: `/api/v1/cases/${caseId}${suffix}` }
    }
    case 'fact.list': return { method: 'GET', url: `/api/v1/cases/${caseId}/facts` }
    case 'fact.update': return { method: 'PUT', url: `/api/v1/cases/${caseId}/facts/${encode(payload.factKey)}`, data: { ...(payload.patch ?? {} as Record<string, unknown>), ...actorBody(payload) } }
    // 时间线：后端没有 timeline 路由（只有 facts / audit / session / messages）。
    // 之前这里映射到一个不存在的地址，接了也只会 404；等后端真正提供接口再加回来。
    case 'audit.list': return { method: 'GET', url: `/api/v1/cases/${caseId}/audit` }
    case 'session.get': return { method: 'GET', url: `/api/v1/cases/${caseId}/session` }
    case 'session.start': return {
      method: 'POST',
      url: `/api/v1/cases/${caseId}/session/start`,
      data: {
        interrogator_officer_id: payload.interrogatorOfficerId ?? null,
        recorder_officer_id: payload.recorderOfficerId ?? null,
        actor_id: payload.actorId,
      },
    }
    case 'session.pause': return { method: 'POST', url: `/api/v1/cases/${caseId}/session/pause`, data: actorBody(payload) }
    case 'session.resume': return { method: 'POST', url: `/api/v1/cases/${caseId}/session/resume`, data: actorBody(payload) }
    case 'session.finish': return { method: 'POST', url: `/api/v1/cases/${caseId}/session/finish`, data: actorBody(payload) }
    case 'session.stage': return { method: 'POST', url: `/api/v1/cases/${caseId}/session/stage`, data: { stage: payload.stage, ...actorBody(payload) } }
    case 'identity.read': return {
      method: 'POST',
      url: '/api/v1/identity/read',
      data: { case_id: payload.caseId, actor_id: payload.actorId },
    }
    case 'identity.confirm': return {
      method: 'POST',
      url: '/api/v1/identity/confirm',
      data: {
        case_id: payload.caseId,
        actor_id: payload.actorId,
        name: payload.name,
        id_number: payload.idNumber,
        gender: payload.gender,
        nation: payload.nation,
        birth_date: payload.birthDate,
        address: payload.address,
        source: payload.source,
        portrait: payload.portrait,
        issuer: payload.issuer,
        valid_from: payload.validFrom,
        valid_to: payload.validTo,
      },
    }
    case 'device.action': return { method: 'POST', url: '/api/v1/device/action', data: { type: payload.type } }
    case 'asr.capture.status': return { method: 'GET', url: `/api/v1/cases/${caseId}/asr/capture` }
    case 'asr.capture.start': return { method: 'POST', url: `/api/v1/cases/${caseId}/asr/capture/start`, data: {} }
    case 'asr.capture.stop': return { method: 'POST', url: `/api/v1/cases/${caseId}/asr/capture/stop`, data: {} }
    case 'asr.fragment.list': return {
      method: 'GET',
      url: `/api/v1/cases/${caseId}/asr/fragments`,
      params: { include_confirmed: payload.includeConfirmed, include_superseded: payload.includeSuperseded },
    }
    case 'asr.fragment.update': return {
      method: 'PUT',
      url: `/api/v1/cases/${caseId}/asr/fragments/${fragmentId}`,
      data: { edited_text: payload.editedText, speaker: payload.speaker, actor_id: payload.actorId, reason: payload.reason },
    }
    case 'asr.fragment.confirm': return { method: 'POST', url: `/api/v1/cases/${caseId}/asr/fragments/${fragmentId}/confirm`, data: {} }
    case 'asr.fragment.confirmBatch': return { method: 'POST', url: `/api/v1/cases/${caseId}/asr/fragments/confirm`, data: { fragment_ids: payload.fragmentIds, ...actorBody(payload) } }
    // 后端 FragmentBatchRequest 的字段是 fragment_ids（无 alias 且 extra="ignore"）。
    // 之前直接透传 payload，发的是 fragmentIds → 后端收到空列表后会退化成
    // "把该案所有待确认片段一次性写入笔录"，属于静默的数据污染。
    case 'asr.fragment.applyToRecord': return { method: 'POST', url: `/api/v1/cases/${caseId}/asr/fragments/apply`, data: { fragment_ids: payload.fragmentIds ?? [], ...actorBody(payload) } }
    case 'asr.fragment.discard': return { method: 'POST', url: `/api/v1/cases/${caseId}/asr/fragments/${fragmentId}/discard`, data: {} }
    case 'voiceprint.readiness': return { method: 'GET', url: `/api/v1/cases/${caseId}/voiceprints/readiness` }
    case 'voiceprint.roleDraft.get': return { method: 'GET', url: `/api/v1/cases/${caseId}/voiceprints/role-draft` }
    case 'voiceprint.enrollment.status': return { method: 'GET', url: '/api/v1/voiceprints/enrollment/status' }
    case 'voiceprint.suspect.enrollment.start': return {
      method: 'POST',
      url: `/api/v1/cases/${caseId}/voiceprints/suspect/enrollment/start`,
      data: { actor_id: payload.actorId },
    }
    case 'voiceprint.suspect.enrollment.stop': return {
      method: 'POST',
      url: `/api/v1/cases/${caseId}/voiceprints/suspect/enrollment/stop`,
      data: { actor_id: payload.actorId },
    }
    case 'officerVoiceprint.list': return {
      method: 'GET',
      url: '/api/v1/officer-voiceprints',
      params: { active_only: payload.activeOnly ?? true },
    }
    case 'officerVoiceprint.enrollment.start': return {
      method: 'POST',
      url: `/api/v1/officer-voiceprints/${officerId}/enrollment/start`,
      data: { officer_name: payload.officerName, actor_id: payload.actorId },
    }
    case 'officerVoiceprint.enrollment.stop': return {
      method: 'POST',
      url: `/api/v1/officer-voiceprints/${officerId}/enrollment/stop`,
      data: { actor_id: payload.actorId },
    }
    case 'officerVoiceprint.revoke': return {
      method: 'DELETE',
      url: `/api/v1/officer-voiceprints/${officerId}`,
      params: { actor_id: payload.actorId },
    }
    case 'voiceprint.assignments.update': return {
      method: 'PUT',
      url: `/api/v1/cases/${caseId}/voiceprints/assignments`,
      data: {
        interrogator_officer_id: payload.interrogatorOfficerId,
        recorder_officer_id: payload.recorderOfficerId,
        actor_id: payload.actorId,
      },
    }
    case 'voiceprint.roleDraft.update': return {
      method: 'PUT',
      url: `/api/v1/cases/${caseId}/voiceprints/role-draft`,
      data: {
        interrogator_officer_id: payload.interrogatorOfficerId,
        recorder_officer_id: payload.recorderOfficerId,
        actor_id: payload.actorId,
      },
    }
    case 'document.signing.get': return { method: 'GET', url: `/api/v1/cases/${caseId}/document` }
    case 'document.freeze': return { method: 'POST', url: `/api/v1/cases/${caseId}/document/freeze`, data: actorBody(payload) }
    case 'document.finalize': return { method: 'POST', url: `/api/v1/cases/${caseId}/document/finalize`, data: actorBody(payload) }
    case 'document.sign': {
      // FastAPI 的 DocumentSignRequest 是 extra="forbid" 的严格模型（85f88dd0 起），
      // caseId 已经在 URL 里，再放进 body 会被判为多余字段直接 422。
      const signature: Record<string, unknown> = {
        signerRole: payload.signerRole,
        signerName: payload.signerName,
        imageDataUrl: payload.imageDataUrl,
        strokesJson: payload.strokesJson,
      }
      if (payload.actorId !== undefined) signature.actorId = payload.actorId
      return { method: 'POST', url: `/api/v1/cases/${caseId}/document/sign`, data: signature }
    }
    case 'case.report.generated': return { method: 'POST', url: `/api/v1/cases/${caseId}/report/generated`, data: actorBody(payload) }
    default: throw new RuntimeAdapterError('UNSUPPORTED_OPERATION', `Linux Runtime 不支持操作：${operation}`, 'NOT_CONFIGURED')
  }
}

export function buildRuntimeWebSocketUrl(origin: string, sessionId: string) {
  const url = new URL(origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `/ws/interrogation/${encodeURIComponent(sessionId)}`
  url.search = ''
  url.hash = ''
  return url.toString().replace(/\/$/, '')
}

function normalizeCapabilityState(value: unknown): RuntimeCapabilityState {
  const normalized = String(value || '').toUpperCase()
  if (['AVAILABLE', 'NOT_CONNECTED', 'NOT_CONFIGURED', 'MODEL_NOT_INSTALLED', 'BUSY', 'ERROR'].includes(normalized)) return normalized as RuntimeCapabilityState
  if (['READY', 'CONNECTED', 'OK', 'IDLE'].includes(normalized)) return 'AVAILABLE'
  if (['MISSING', 'NOT_INSTALLED'].includes(normalized)) return 'MODEL_NOT_INSTALLED'
  return 'NOT_CONFIGURED'
}

function capabilityFallback(reason: string) {
  const result = capabilitySet('NOT_CONFIGURED', reason)
  result.asr = capability('asr', 'MODEL_NOT_INSTALLED', 'ASR 模型/运行时尚未安装')
  result.ocr = capability('ocr', 'MODEL_NOT_INSTALLED', 'OCR 模型/运行时尚未安装')
  result.llm = capability('llm', 'MODEL_NOT_INSTALLED', 'LLM 模型/运行时尚未安装')
  result.recording = capability('recording', 'MODEL_NOT_INSTALLED', '连续 ASR 模型/运行时尚未安装')
  return result
}

export class LinuxHttpWsAdapter implements RuntimeAdapter {
  readonly kind = 'linux-http-ws' as const
  private readonly request: RuntimeHttpRequest
  private readonly origin: string
  private readonly WebSocketCtor?: RuntimeWebSocketConstructor
  private capabilitiesCache?: RuntimeCapabilities

  constructor(options: LinuxAdapterOptions = {}) {
    this.request = options.request || (async <T>(config: RuntimeHttpRequestConfig) => {
      const response = await http.request<T>(config as AxiosRequestConfig)
      return { data: response.data }
    })
    this.origin = options.origin || (typeof window !== 'undefined' ? window.location.origin : runtimeConfig.apiBaseUrl)
    this.WebSocketCtor = options.WebSocketCtor
  }

  async invoke<T>(operation: RuntimeOperation, payload: Record<string, unknown> = {}, options: RuntimeInvokeOptions = {}): Promise<T> {
    let browserBackendStarted = false
    try {
      const stoppingBrowserCapture = audioInputMode === 'BROWSER' && (operation === 'asr.capture.stop' || operation === 'document.finalize')
      if (stoppingBrowserCapture) await stopBrowserAsrCapture()
      const config = endpoint(operation, payload)
      if (options.timeoutMs) config.timeout = options.timeoutMs
      const response = await this.request<T>(config)
      const result = unwrap<T>(response.data)

      if (stoppingBrowserCapture) await confirmBrowserAsrCaptureFinalized()

      if (audioInputMode === 'BROWSER' && operation === 'asr.capture.start' && typeof window !== 'undefined') {
        browserBackendStarted = true
        const raw = result && typeof result === 'object' ? result as Record<string, unknown> : {}
        const captureId = String(raw.captureSessionId ?? raw.capture_session_id ?? '')
        if (!captureId) throw new Error('Linux 后端未返回 ASR captureSessionId，无法建立局域网浏览器音频通道')
        await startBrowserAsrCapture(String(payload.caseId ?? ''), captureId, runtimeConfig.apiBaseUrl)
      }

      return result
    } catch (error) {
      if (
        audioInputMode === 'BROWSER'
        && operation === 'asr.capture.start'
        && error instanceof BrowserFormalCaptureLeaseError
        && error.reason === 'CONFLICT'
      ) {
        // This tab does not own the capture lease. Keep the backend capture
        // alive for the tab that does own its microphone and durable outbox.
      } else if (audioInputMode === 'BROWSER' && operation === 'asr.capture.start') {
        if (browserBackendStarted) {
          // The browser outbox must drain or receive an explicit incomplete
          // acknowledgement before the backend is allowed to finalize.
          await stopBrowserAsrCapture()
          try {
            await this.request(endpoint('asr.capture.stop', payload))
            await confirmBrowserAsrCaptureFinalized()
          } catch { /* preserve original failure and lease if cleanup failed */ }
        } else {
          await stopBrowserAsrCapture().catch(() => undefined)
        }
      } else if (audioInputMode === 'BROWSER' && (operation === 'asr.capture.stop' || operation === 'document.finalize')) {
        await stopBrowserAsrCapture().catch(() => undefined)
      }
      throw normalizeRuntimeError(error, operation)
    }
  }

  async getCapabilities(force = false): Promise<RuntimeCapabilities> {
    if (this.capabilitiesCache && !force) return this.capabilitiesCache
    try {
      const response = await this.request<unknown>({ method: 'GET', url: '/api/v1/capabilities' })
      const raw = unwrap<unknown>(response.data)
      const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
      const fallback = capabilityFallback('Linux 后端未声明该能力')
      const names = Object.keys(fallback) as RuntimeCapabilityName[]
      const result = { ...fallback }
      for (const name of names) {
        const value = source[name]
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const record = value as Record<string, unknown>
          result[name] = capability(
            name,
            normalizeCapabilityState(record.state ?? record.status),
            typeof record.reason === 'string' ? record.reason : typeof record.message === 'string' ? record.message : undefined,
            record,
          )
        } else if (value !== undefined) {
          result[name] = capability(name, normalizeCapabilityState(value))
        }
      }
      this.capabilitiesCache = result
      return result
    } catch (error) {
      const normalized = normalizeRuntimeError(error, 'capabilities.get')
      if (normalized.state === 'NOT_CONNECTED') this.capabilitiesCache = capabilitySet('NOT_CONNECTED', normalized.message)
      else this.capabilitiesCache = capabilityFallback('Linux 后端尚未实现 capability endpoint')
      return this.capabilitiesCache
    }
  }

  connectSession(sessionId: string, listener: RuntimeEventListener): RuntimeSessionConnection {
    const client = new RuntimeWebSocketClient({
      url: buildRuntimeWebSocketUrl(this.origin, sessionId),
      sessionId,
      onEvent: listener,
      ...(this.WebSocketCtor ? { WebSocketCtor: this.WebSocketCtor } : {}),
    })
    client.connect()
    return client
  }
}
