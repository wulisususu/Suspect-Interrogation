import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RuntimeWebSocketClient } from '../wsClient'

class FakeSocket {
  static instances: FakeSocket[] = []
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readonly url: string
  readyState = FakeSocket.CONNECTING
  sent: string[] = []
  onopen: ((event: unknown) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  send(data: string) { this.sent.push(data) }

  open() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.({})
  }

  message(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  failClose(code = 1006) {
    this.readyState = FakeSocket.CLOSED
    this.onclose?.({ code })
  }

  close() {
    this.readyState = FakeSocket.CLOSED
  }
}

describe('RuntimeWebSocketClient', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeSocket.instances = []
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reconnects with backoff and resyncs the accepted sequence', async () => {
    const client = new RuntimeWebSocketClient({
      url: 'ws://127.0.0.1/ws/interrogation/session-1',
      sessionId: 'session-1',
      WebSocketCtor: FakeSocket as never,
      backoffMs: [10, 20],
    })

    client.connect()
    expect(FakeSocket.instances).toHaveLength(1)
    FakeSocket.instances[0]!.open()
    FakeSocket.instances[0]!.message({ id: 'evt-7', seq: 7, event: 'SESSION_STATE', payload: { status: 'RUNNING' } })
    FakeSocket.instances[0]!.failClose()

    await vi.advanceTimersByTimeAsync(9)
    expect(FakeSocket.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeSocket.instances).toHaveLength(2)

    FakeSocket.instances[1]!.open()
    const resync = FakeSocket.instances[1]!.sent.map((item) => JSON.parse(item))
    expect(resync).toHaveLength(1)
    expect(resync[0]).toMatchObject({
      session_id: 'session-1',
      event: 'STATE_SYNC_REQUEST',
      seq: 7,
      payload: { last_seq: 7 },
    })
    expect(typeof resync[0].timestamp).toBe('string')

    client.close()
  })

  it('resets the sequence watermark when the backend process epoch changes', () => {
    const received: string[] = []
    const client = new RuntimeWebSocketClient({
      url: 'ws://127.0.0.1/ws/interrogation/session-3',
      sessionId: 'session-3',
      WebSocketCtor: FakeSocket as never,
      onEvent: (event) => received.push(`${event.event}:${event.seq}`),
    })

    client.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    socket.message({ epoch: 'boot-a', seq: 40, event: 'ASR_FINAL', payload: {} })
    socket.message({ epoch: 'boot-a', seq: 41, event: 'ASR_FINAL', payload: {} })
    socket.message({ epoch: 'boot-a', seq: 40, event: 'ASR_FINAL', payload: {} })

    // 后端重启：epoch 变了，seq 从 1 重新开始，不能当成旧消息丢掉。
    socket.message({ epoch: 'boot-b', seq: 1, event: 'RECORDING_STATE', payload: { running: true } })
    socket.message({ epoch: 'boot-b', seq: 2, event: 'SESSION_STATE', payload: { status: 'PAUSED' } })

    expect(received).toEqual([
      'ASR_FINAL:40',
      'ASR_FINAL:41',
      'RECORDING_STATE:1',
      'SESSION_STATE:2',
    ])
    client.close()
  })

  it('drops duplicate ids and non-increasing sequence numbers', () => {
    const received: string[] = []
    const client = new RuntimeWebSocketClient({
      url: 'ws://127.0.0.1/ws/interrogation/session-2',
      sessionId: 'session-2',
      WebSocketCtor: FakeSocket as never,
      onEvent: (event) => received.push(event.id || `${event.seq}`),
    })

    client.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    socket.message({ id: 'a', seq: 1, event: 'ASR_PARTIAL', payload: { text: '一' } })
    socket.message({ id: 'a', seq: 1, event: 'ASR_PARTIAL', payload: { text: '一' } })
    socket.message({ id: 'older', seq: 1, event: 'ASR_FINAL', payload: { text: '旧' } })
    socket.message({ id: 'b', seq: 2, event: 'ASR_FINAL', payload: { text: '一二' } })

    expect(received).toEqual(['a', 'b'])
    client.close()
  })
})
