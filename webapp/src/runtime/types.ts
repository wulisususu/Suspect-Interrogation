export type RuntimeKind = 'linux-http-ws' | 'browser-dev'

export type RuntimeCapabilityState =
  | 'AVAILABLE'
  | 'NOT_CONNECTED'
  | 'NOT_CONFIGURED'
  | 'MODEL_NOT_INSTALLED'
  | 'BUSY'
  | 'ERROR'

export type RuntimeCapabilityName =
  | 'identity'
  | 'camera'
  | 'microphone'
  | 'fingerprint'
  | 'signature'
  | 'recording'
  | 'asr'
  | 'ocr'
  | 'llm'
  | 'report'

export interface RuntimeCapability {
  name: RuntimeCapabilityName
  state: RuntimeCapabilityState
  reason?: string
  metadata?: Record<string, unknown>
}

export type RuntimeCapabilities = Record<RuntimeCapabilityName, RuntimeCapability>

export type RuntimeOperation = string

export interface RuntimeEvent<T = unknown> {
  id?: string
  seq?: number
  /** 服务端进程实例标识；后端重启后 seq 会从 1 重新计数，靠它识别换代。 */
  epoch?: string
  event: string
  payload: T
  receivedAt: number
}

export type RuntimeEventListener = (event: RuntimeEvent) => void
export type RuntimeConnectionState = 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'

export interface RuntimeSessionConnection {
  close(): void
  send(event: string, payload?: Record<string, unknown>): boolean
}

export interface RuntimeInvokeOptions {
  timeoutMs?: number
}

export interface RuntimeAdapter {
  readonly kind: RuntimeKind
  invoke<T>(operation: RuntimeOperation, payload?: Record<string, unknown>, options?: RuntimeInvokeOptions): Promise<T>
  getCapabilities(force?: boolean): Promise<RuntimeCapabilities>
  connectSession(sessionId: string, listener: RuntimeEventListener): RuntimeSessionConnection
}

export function capability(
  name: RuntimeCapabilityName,
  state: RuntimeCapabilityState,
  reason?: string,
  metadata?: Record<string, unknown>,
): RuntimeCapability {
  return { name, state, ...(reason ? { reason } : {}), ...(metadata ? { metadata } : {}) }
}

export function capabilitySet(
  state: RuntimeCapabilityState,
  reason?: string,
): RuntimeCapabilities {
  return {
    identity: capability('identity', state, reason),
    camera: capability('camera', state, reason),
    microphone: capability('microphone', state, reason),
    fingerprint: capability('fingerprint', state, reason),
    signature: capability('signature', state, reason),
    recording: capability('recording', state, reason),
    asr: capability('asr', state, reason),
    ocr: capability('ocr', state, reason),
    llm: capability('llm', state, reason),
    report: capability('report', state, reason),
  }
}
