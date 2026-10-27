import type {
  RuntimeConnectionState,
  RuntimeEvent,
  RuntimeEventListener,
  RuntimeSessionConnection,
} from './types'

export interface RuntimeWebSocketLike {
  readyState: number
  onopen: ((event: unknown) => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onerror: ((event: unknown) => void) | null
  onclose: ((event: { code: number }) => void) | null
  send(data: string): void
  close(): void
}

export type RuntimeWebSocketConstructor = new (url: string) => RuntimeWebSocketLike

export interface RuntimeWebSocketClientOptions {
  url: string
  sessionId: string
  WebSocketCtor?: RuntimeWebSocketConstructor
  backoffMs?: number[]
  onEvent?: RuntimeEventListener
  onConnectionState?: (state: RuntimeConnectionState) => void
}

const DEFAULT_BACKOFF = [250, 500, 1000, 2000, 5000]
const MAX_SEEN_IDS = 512

function normalizeEvent(raw: Record<string, unknown>): RuntimeEvent {
  const eventName = typeof raw.event === 'string'
    ? raw.event
    : typeof raw.type === 'string'
      ? raw.type
      : 'UNKNOWN'
  const payload = raw.payload !== undefined
    ? raw.payload
    : Object.fromEntries(Object.entries(raw).filter(([key]) => !['event', 'type', 'id', 'seq', 'epoch'].includes(key)))

  return {
    ...(typeof raw.id === 'string' ? { id: raw.id } : {}),
    ...(typeof raw.seq === 'number' && Number.isFinite(raw.seq) ? { seq: raw.seq } : {}),
    ...(typeof raw.epoch === 'string' && raw.epoch ? { epoch: raw.epoch } : {}),
    event: eventName,
    payload,
    receivedAt: Date.now(),
  }
}

export class RuntimeWebSocketClient implements RuntimeSessionConnection {
  private socket?: RuntimeWebSocketLike
  private reconnectTimer?: ReturnType<typeof setTimeout>
  private closedByClient = false
  private reconnectAttempt = 0
  private openedBefore = false
  private lastSeq = 0
  private epoch?: string
  private readonly seenIds = new Set<string>()
  private readonly seenIdOrder: string[] = []
  private readonly WebSocketCtor: RuntimeWebSocketConstructor
  private readonly backoffMs: number[]

  constructor(private readonly options: RuntimeWebSocketClientOptions) {
    const nativeCtor = typeof WebSocket !== 'undefined' ? WebSocket : undefined
    const ctor = options.WebSocketCtor || nativeCtor
    if (!ctor) throw new Error('当前环境没有 WebSocket 实现')
    this.WebSocketCtor = ctor as unknown as RuntimeWebSocketConstructor
    this.backoffMs = options.backoffMs?.length ? options.backoffMs : DEFAULT_BACKOFF
  }

  connect() {
    this.closedByClient = false
    this.clearReconnectTimer()
    this.openSocket(this.openedBefore ? 'RECONNECTING' : 'CONNECTING')
  }

  private openSocket(state: RuntimeConnectionState) {
    this.options.onConnectionState?.(state)
    const socket = new this.WebSocketCtor(this.options.url)
    this.socket = socket

    socket.onopen = () => {
      if (this.socket !== socket || this.closedByClient) return
      const isReconnect = this.openedBefore
      this.openedBefore = true
      this.reconnectAttempt = 0
      this.options.onConnectionState?.('CONNECTED')
      if (isReconnect) {
        // 后端要求的信封字段一个都不能少（session_id / event / seq / timestamp），
        // 否则只会换回一条 PROTOCOL_ERROR。
        this.send('STATE_SYNC_REQUEST', {
          session_id: this.options.sessionId,
          last_seq: this.lastSeq,
        })
      }
    }

    socket.onmessage = (message) => {
      if (this.socket !== socket || this.closedByClient) return
      let raw: unknown
      try {
        raw = JSON.parse(message.data)
      } catch {
        return
      }
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return
      const event = normalizeEvent(raw as Record<string, unknown>)
      if (!this.acceptEvent(event)) return
      this.options.onEvent?.(event)
    }

    socket.onerror = () => {
      if (this.socket === socket && !this.closedByClient) this.options.onConnectionState?.('RECONNECTING')
    }

    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = undefined
      if (this.closedByClient) {
        this.options.onConnectionState?.('DISCONNECTED')
        return
      }
      this.scheduleReconnect()
    }
  }

  private acceptEvent(event: RuntimeEvent) {
    if (event.epoch && event.epoch !== this.epoch) {
      // 服务端进程换过了：它的 seq 存在内存里，重启后从 1 重新开始。
      // 不清零就会把重启后的新消息全部当成旧消息丢掉（每次部署都会重启运行时）。
      this.epoch = event.epoch
      this.lastSeq = 0
      this.seenIds.clear()
      this.seenIdOrder.length = 0
    }
    if (event.id && this.seenIds.has(event.id)) return false
    if (event.seq !== undefined && event.seq <= this.lastSeq) return false

    if (event.id) {
      this.seenIds.add(event.id)
      this.seenIdOrder.push(event.id)
      if (this.seenIdOrder.length > MAX_SEEN_IDS) {
        const oldest = this.seenIdOrder.shift()
        if (oldest) this.seenIds.delete(oldest)
      }
    }
    if (event.seq !== undefined) this.lastSeq = event.seq
    return true
  }

  private scheduleReconnect() {
    this.clearReconnectTimer()
    this.options.onConnectionState?.('RECONNECTING')
    const index = Math.min(this.reconnectAttempt, this.backoffMs.length - 1)
    const delay = this.backoffMs[index] ?? DEFAULT_BACKOFF[DEFAULT_BACKOFF.length - 1]
    this.reconnectAttempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined
      if (!this.closedByClient) this.openSocket('RECONNECTING')
    }, delay)
  }

  send(event: string, payload: Record<string, unknown> = {}) {
    if (!this.socket || this.socket.readyState !== 1) return false
    this.socket.send(JSON.stringify({
      session_id: this.options.sessionId,
      event,
      seq: this.lastSeq,
      timestamp: new Date().toISOString(),
      payload,
    }))
    return true
  }

  close() {
    this.closedByClient = true
    this.clearReconnectTimer()
    const socket = this.socket
    this.socket = undefined
    socket?.close()
    this.options.onConnectionState?.('DISCONNECTED')
  }

  private clearReconnectTimer() {
    if (!this.reconnectTimer) return
    clearTimeout(this.reconnectTimer)
    this.reconnectTimer = undefined
  }
}
