import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  acquireBrowserFormalCaptureLease,
  BrowserFormalCaptureLease,
  BrowserFormalCaptureLeaseError,
  buildBrowserAsrCaptureWebSocketUrl,
  buildBrowserQuestionPreparationWebSocketUrl,
  BoundedBrowserAsrOutbox,
  BrowserFormalIncompleteMarker,
  confirmBrowserAsrCaptureFinalized,
  confirmBrowserFormalOutboxFinalization,
  clearBrowserAsrCaptureLeaseRefusal,
  encodeBrowserFormalAsrFrame,
  reconcileBrowserFormalCursor,
  removeBrowserFormalFrameAfterDurableAck,
  sendNextBrowserFormalFrame,
  startBrowserQuestionPreparationCapture,
  startBrowserAsrCapture,
  stopBrowserAsrCapture,
  stopBrowserQuestionPreparationCapture,
  takeMatchingBrowserFormalFinalization,
  waitForBrowserFormalOutboxDrain,
} from './browserAsrCapture'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})


describe('LAN browser ASR websocket URLs', () => {
  it('keeps legacy HTTP formal interrogation audio on the same LAN origin', () => {
    expect(buildBrowserAsrCaptureWebSocketUrl(
      'CASE 1',
      'capture/1',
      'http://192.168.1.50:18080',
    )).toBe('ws://192.168.1.50:18080/ws/asr/cases/CASE%201/capture/capture%2F1')
  })

  it('uses WSS for formal interrogation audio on the production HTTPS origin', () => {
    expect(buildBrowserAsrCaptureWebSocketUrl(
      'CASE 1',
      'capture/1',
      'https://192.168.0.9:18080',
    )).toBe('wss://192.168.0.9:18080/ws/asr/cases/CASE%201/capture/capture%2F1')
  })

  it('uses WSS for question preparation on an HTTPS origin', () => {
    expect(buildBrowserQuestionPreparationWebSocketUrl(
      'CASE 1',
      'prep/1',
      'https://192.168.0.9:18080',
    )).toBe('wss://192.168.0.9:18080/ws/asr/cases/CASE%201/question-preparation/prep%2F1')
  })
})

describe('formal browser ASR frame durability helpers', () => {
  it('advances a stale cursor past the last frame persisted before a crash', () => {
    expect(reconcileBrowserFormalCursor(
      { nextSequence: 2, nextStartSample: 100n },
      [{ sequence: 2, startSample: 100n, pcm: new Uint8Array([7, 8, 9, 10]) }],
    )).toEqual({ nextSequence: 3, nextStartSample: 102n })
  })

  it('encodes sequence and sample start in the formal little-endian header', () => {
    const encoded = new Uint8Array(encodeBrowserFormalAsrFrame(
      0x01020304,
      0x0102030405060708n,
      new Uint8Array([0x11, 0x22]),
    ))

    expect(Array.from(encoded)).toEqual([
      4, 3, 2, 1,
      8, 7, 6, 5, 4, 3, 2, 1,
      0x11, 0x22,
    ])
  })

  it('rejects frames that exceed the bounded durable outbox capacity', async () => {
    const rows = new Map<number, { sequence: number; startSample: bigint; pcm: Uint8Array }>()
    let progress: { nextSequence: number; nextStartSample: bigint } | null = null
    const store = {
      list: async () => [...rows.values()],
      put: async (frame) => { rows.set(frame.sequence, frame) },
      delete: async (sequence) => { rows.delete(sequence) },
      clear: async () => { rows.clear() },
      loadProgress: async () => progress,
      saveProgress: async (nextSequence: number, nextStartSample: bigint) => {
        progress = { nextSequence, nextStartSample }
      },
    }
    const outbox = new BoundedBrowserAsrOutbox(store, 4)
    await outbox.append({ sequence: 1, startSample: 0n, pcm: new Uint8Array([1, 2, 3, 4]) })

    await expect(outbox.append({
      sequence: 2,
      startSample: 2n,
      pcm: new Uint8Array([5, 6]),
    })).rejects.toThrow(/capacity/i)
    expect((await outbox.list()).map((frame) => frame.sequence)).toEqual([1])
  })

  it('keeps the next sequence/sample cursor when every audio frame is acknowledged', async () => {
    let progress: { nextSequence: number; nextStartSample: bigint } | null = null
    const store = {
      list: async () => [],
      put: async () => undefined,
      delete: async () => undefined,
      clear: async () => { progress = null },
      loadProgress: async () => progress,
      saveProgress: async (nextSequence: number, nextStartSample: bigint) => {
        progress = { nextSequence, nextStartSample }
      },
    }
    const outbox = new BoundedBrowserAsrOutbox(store, 4)
    await outbox.saveProgress(23, 320_000n)

    expect(await outbox.list()).toEqual([])
    expect(await outbox.loadProgress()).toEqual({ nextSequence: 23, nextStartSample: 320_000n })
  })

  it('replays the lowest unacknowledged sequence after reconnect', async () => {
    const rows = [
      { sequence: 3, startSample: 4n, pcm: new Uint8Array([5, 6]) },
      { sequence: 2, startSample: 2n, pcm: new Uint8Array([3, 4]) },
    ]
    const outbox = { list: async () => rows }
    const sent: ArrayBuffer[] = []

    const frame = await sendNextBrowserFormalFrame(
      { readyState: 1, send: (data: ArrayBuffer) => { sent.push(data) } },
      outbox,
    )

    expect(frame?.sequence).toBe(2)
    expect(Array.from(new Uint8Array(sent[0]))).toEqual([
      2, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 3, 4,
    ])
  })

  it('waits for all persisted frames to be acknowledged before allowing stop', async () => {
    let pending = [{ sequence: 1, startSample: 0n, pcm: new Uint8Array([1, 2]) }]
    const outbox = { list: async () => pending }
    let sendAttempts = 0
    const drained = await waitForBrowserFormalOutboxDrain(outbox, async () => {
      sendAttempts += 1
      if (sendAttempts === 2) pending = []
    }, 100)

    expect(drained).toBe(true)
    expect(sendAttempts).toBe(2)
  })

  it('allows stop after an explicit incomplete acknowledgement while retaining pending frames', async () => {
    const pending = [{ sequence: 4, startSample: 6n, pcm: new Uint8Array([7, 8]) }]
    let incompleteConfirmed = false
    const drained = waitForBrowserFormalOutboxDrain(
      { list: async () => pending },
      async () => { incompleteConfirmed = true },
      100,
      () => incompleteConfirmed,
    )

    expect(await drained).toBe(true)
    expect(pending.map((frame) => frame.sequence)).toEqual([4])
  })

  it('does not clear pending frames or cursor after incomplete finalization', async () => {
    const rows = new Map<number, { sequence: number; startSample: bigint; pcm: Uint8Array }>([
      [4, { sequence: 4, startSample: 6n, pcm: new Uint8Array([7, 8]) }],
    ])
    let progress: { nextSequence: number; nextStartSample: bigint } | null = {
      nextSequence: 5,
      nextStartSample: 7n,
    }
    const outbox = new BoundedBrowserAsrOutbox({
      list: async () => [...rows.values()],
      put: async (frame) => { rows.set(frame.sequence, frame) },
      delete: async (sequence) => { rows.delete(sequence) },
      clear: async () => { rows.clear(); progress = null },
      loadProgress: async () => progress,
      saveProgress: async (nextSequence, nextStartSample) => {
        progress = { nextSequence, nextStartSample }
      },
    }, 1024)

    await confirmBrowserFormalOutboxFinalization(outbox, true)

    expect((await outbox.list()).map((frame) => frame.sequence)).toEqual([4])
    expect(await outbox.loadProgress()).toEqual({ nextSequence: 5, nextStartSample: 7n })
  })

  it('retries an incomplete control after reconnect when its application ack was lost', () => {
    const marker = new BrowserFormalIncompleteMarker()
    const reason = 'browser storage failure'

    expect(marker.shouldSend({ failed: true, reason, pendingCount: 0 })).toBe(true)
    expect(marker.shouldSend({ failed: true, reason, pendingCount: 1 })).toBe(false)
    expect(marker.shouldSend({
      failed: true,
      reason,
      pendingCount: 1,
      mayBypassPending: true,
    })).toBe(true)
    marker.markSent()
    expect(marker.shouldSend({ failed: true, reason, pendingCount: 0 })).toBe(false)
    marker.onSocketClosed()
    expect(marker.shouldSend({ failed: true, reason, pendingCount: 0 })).toBe(true)
    marker.markSent()
    marker.confirm()
    marker.onSocketClosed()
    expect(marker.shouldSend({ failed: true, reason, pendingCount: 0 })).toBe(false)
  })

  it('keeps a durably acknowledged frame when local IndexedDB deletion fails', async () => {
    const pending = [{ sequence: 1, startSample: 0n, pcm: new Uint8Array([1, 2]) }]
    const failure = new Error('IndexedDB delete failed')
    let reported: unknown = null
    const outbox = {
      list: async () => pending,
      acknowledge: async () => { throw failure },
    }
    const removed = await removeBrowserFormalFrameAfterDurableAck(
      outbox,
      1,
      (error) => { reported = error },
    )

    expect(removed).toBe(false)
    expect(reported).toBe(failure)
    expect((await outbox.list()).map((frame) => frame.sequence)).toEqual([1])
  })
})

describe('question preparation capture replacement', () => {
  it('stops the prior stream and opens the requested new URL', async () => {
    const sockets: Array<{ url: string; readyState: number; onopen?: () => void; onclose?: () => void }> = []
    const tracks = [{ stop: vi.fn() }]
    const getUserMedia = vi.fn(async () => ({ getTracks: () => tracks }))

    class FakeWebSocket {
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3
      readyState = 0
      binaryType = ''
      onopen?: () => void
      onclose?: () => void
      constructor(readonly url: string) {
        sockets.push(this)
        queueMicrotask(() => {
          this.readyState = FakeWebSocket.OPEN
          this.onopen?.()
        })
      }
      send() {}
      close() {
        this.readyState = FakeWebSocket.CLOSED
        this.onclose?.()
      }
    }

    class FakeAudioContext {
      state = 'running'
      sampleRate = 16_000
      destination = {}
      async resume() {}
      async close() { this.state = 'closed' }
      createMediaStreamSource() { return { connect() {}, disconnect() {} } }
      createAnalyser() {
        return {
          fftSize: 0,
          smoothingTimeConstant: 0,
          connect() {},
          disconnect() {},
          getFloatTimeDomainData(samples: Float32Array) { samples.fill(0) },
        }
      }
      createScriptProcessor() { return { onaudioprocess: null, connect() {}, disconnect() {} } }
      createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} } }
    }

    vi.stubGlobal('window', {
      isSecureContext: true,
      setTimeout: (handler: TimerHandler, timeout?: number) => setTimeout(handler, timeout) as unknown as number,
      clearTimeout: (timer: number) => clearTimeout(timer),
      setInterval: (handler: TimerHandler, timeout?: number) => setInterval(handler, timeout) as unknown as number,
      clearInterval: (timer: number) => clearInterval(timer),
    })
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('AudioContext', FakeAudioContext)

    try {
      const oldUrl = 'wss://lan.example/ws/asr/cases/CASE-A/question-preparation/PREP-1'
      const newUrl = 'wss://lan.example/ws/asr/cases/CASE-A/question-preparation/PREP-2'
      await startBrowserQuestionPreparationCapture('CASE-A', 'PREP-1', 'https://lan.example')
      await startBrowserQuestionPreparationCapture('CASE-A', 'PREP-2', 'https://lan.example')

      expect(sockets.map((socket) => socket.url)).toEqual([oldUrl, newUrl])
      expect(sockets[0]?.readyState).toBe(FakeWebSocket.CLOSED)
      expect(sockets[1]?.readyState).toBe(FakeWebSocket.OPEN)
      expect(getUserMedia).toHaveBeenCalledTimes(2)
    } finally {
      await stopBrowserQuestionPreparationCapture()
    }
  })
})

describe('cross-tab formal browser capture lease', () => {
  it('reuses only the pending finalization lease for the same capture', () => {
    const lease = new BrowserFormalCaptureLease(() => undefined, Promise.resolve())
    const pending = { captureKey: 'CASE-D:CAPTURE-D', lease }

    expect(takeMatchingBrowserFormalFinalization(pending, 'CASE-D:CAPTURE-D')).toEqual({
      resumed: pending,
      remaining: null,
    })
    expect(takeMatchingBrowserFormalFinalization(pending, 'CASE-E:CAPTURE-E')).toEqual({
      resumed: null,
      remaining: pending,
    })
  })

  it('does not treat unsupported browser locks as an existing tab ownership conflict', async () => {
    vi.stubGlobal('navigator', {})

    await expect(startBrowserAsrCapture('CASE-B', 'CAPTURE-B', 'https://lan.example'))
      .rejects.toMatchObject({ reason: 'UNSUPPORTED' })
    await expect(stopBrowserAsrCapture()).resolves.toBeUndefined()
  })

  it('rejects a second tab without opening audio or allowing it to stop the capture', async () => {
    const heldLocks = new Set<string>()
    const locks = {
      async request(
        name: string,
        _options: unknown,
        callback: (lock: Lock | null) => Promise<void>,
      ) {
        if (heldLocks.has(name)) return callback(null)
        heldLocks.add(name)
        try {
          return await callback({ name } as Lock)
        } finally {
          heldLocks.delete(name)
        }
      },
    }
    vi.stubGlobal('navigator', { locks })
    const captureKey = 'CASE-A:CAPTURE-A'
    const lockName = `suspect-interrogation:formal-audio:${captureKey}`
    const firstTab = await acquireBrowserFormalCaptureLease(captureKey)

    expect(heldLocks.has(lockName)).toBe(true)
    await expect(startBrowserAsrCapture('CASE-A', 'CAPTURE-A', 'https://lan.example'))
      .rejects.toBeInstanceOf(BrowserFormalCaptureLeaseError)
    expect(heldLocks.has(lockName)).toBe(true)
    await expect(stopBrowserAsrCapture()).rejects.toBeInstanceOf(BrowserFormalCaptureLeaseError)

    firstTab.release()
    await firstTab.completion
    clearBrowserAsrCaptureLeaseRefusal('CASE-A', 'CAPTURE-A')
    expect(heldLocks.has(lockName)).toBe(false)
  })

  it('allows a newer capture stop retry after it acquires the lease following an older capture conflict', async () => {
    const heldLocks = new Set<string>()
    const locks = {
      async request(
        name: string,
        _options: unknown,
        callback: (lock: Lock | null) => Promise<void>,
      ) {
        if (heldLocks.has(name)) return callback(null)
        heldLocks.add(name)
        try {
          return await callback({ name } as Lock)
        } finally {
          heldLocks.delete(name)
        }
      },
    }
    vi.stubGlobal('navigator', { locks })

    const oldTab = await acquireBrowserFormalCaptureLease('CASE-A:CAPTURE-A')
    await expect(startBrowserAsrCapture('CASE-A', 'CAPTURE-A', 'https://lan.example'))
      .rejects.toBeInstanceOf(BrowserFormalCaptureLeaseError)
    oldTab.release()
    await oldTab.completion

    const startingNewCapture = startBrowserAsrCapture('CASE-B', 'CAPTURE-B', 'https://lan.example')
    await expect(stopBrowserAsrCapture()).resolves.toBeUndefined()
    await expect(startingNewCapture).rejects.toMatchObject({ name: 'BrowserCaptureStartupCancelledError' })

    // This is the adapter's retry after the first backend stop failed. It must not be
    // blocked by the stale conflict recorded for CASE-A.
    await expect(stopBrowserAsrCapture()).resolves.toBeUndefined()
  })

  it('cancels startup when stop arrives while the cross-tab lease is being acquired', async () => {
    const locks = {
      async request(
        name: string,
        _options: unknown,
        callback: (lock: Lock | null) => Promise<void>,
      ) {
        return callback({ name } as Lock)
      },
    }
    const getUserMedia = vi.fn()
    vi.stubGlobal('navigator', { locks, mediaDevices: { getUserMedia } })

    const starting = startBrowserAsrCapture('CASE-C', 'CAPTURE-C', 'https://lan.example')
    const stopping = stopBrowserAsrCapture()

    await expect(starting).rejects.toMatchObject({ name: 'BrowserCaptureStartupCancelledError' })
    await expect(stopping).resolves.toBeUndefined()
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('keeps a failed formal startup available for stop retry when outbox drain cannot complete', async () => {
    vi.useFakeTimers()
    let lockHeld = false
    let waitForUnlock: Promise<void> = Promise.resolve()
    const locks = {
      async request(
        _name: string,
        _options: unknown,
        callback: (lock: Lock | null) => Promise<void>,
      ) {
        if (lockHeld) return callback(null)
        lockHeld = true
        try {
          waitForUnlock = callback({} as Lock)
          return await waitForUnlock
        } finally {
          lockHeld = false
        }
      },
    }
    const sockets: Array<{
      readyState: number
      sent: unknown[]
      onopen?: () => void
      onclose?: (event: { code: number; reason: string }) => void
      onmessage?: (event: { data: unknown }) => void
    }> = []
    class FakeWebSocket {
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3
      readyState = 0
      binaryType = ''
      sent: unknown[] = []
      onopen?: () => void
      onclose?: (event: { code: number; reason: string }) => void
      onmessage?: (event: { data: unknown }) => void
      constructor() {
        sockets.push(this)
        queueMicrotask(() => {
          this.readyState = FakeWebSocket.OPEN
          this.onopen?.()
        })
      }
      send(data: unknown) { this.sent.push(data) }
      close(code = 1000, reason = '') {
        this.readyState = FakeWebSocket.CLOSED
        this.onclose?.({ code, reason })
      }
    }
    vi.stubGlobal('window', {
      setTimeout: (handler: TimerHandler, timeout?: number) => setTimeout(handler, timeout) as unknown as number,
      clearTimeout: (timer: number) => clearTimeout(timer),
    })
    vi.stubGlobal('navigator', { locks })
    vi.stubGlobal('indexedDB', undefined)
    vi.stubGlobal('WebSocket', FakeWebSocket)

    const starting = startBrowserAsrCapture('CASE-F', 'CAPTURE-F', 'https://lan.example')
    const startupFailure = expect(starting).rejects.toThrow('未获服务器确认')
    await vi.advanceTimersByTimeAsync(10_000)
    await startupFailure
    const socket = sockets.find((item) => item.sent.some((value) => typeof value === 'string'))
    expect(socket).toBeDefined()
    expect(lockHeld).toBe(true)

    socket?.onmessage?.({ data: JSON.stringify({ type: 'capture_incomplete_ack' }) })
    await Promise.resolve()
    await stopBrowserAsrCapture()
    expect(lockHeld).toBe(true)

    await confirmBrowserAsrCaptureFinalized()
    await waitForUnlock
    expect(lockHeld).toBe(false)
  })
})

describe('clean stop handshake', () => {
  it('declares a clean stop before closing the formal socket', async () => {
    const source = (await import('./browserAsrCapture.ts?raw')).default
    const finalizeAt = source.indexOf("type: 'capture_finalize'")
    const closeAt = source.indexOf("this.socket.close(1000, 'capture stopped')")
    expect(finalizeAt).toBeGreaterThan(-1)
    expect(closeAt).toBeGreaterThan(-1)
    // 必须先声明干净停止再关闭：否则后端只能按断线处理，采集会被记为 INCOMPLETE。
    expect(finalizeAt).toBeLessThan(closeAt)
    expect(source).toContain("this.kind === 'FORMAL'")
  })
})

describe('duplicate capture socket', () => {
  it('stops quietly when the server refuses a second connection to the same capture', async () => {
    const source = (await import('./browserAsrCapture.ts?raw')).default
    const start = source.indexOf('if (event.code === 4429)')
    expect(start).toBeGreaterThan(-1)
    const branch = source.slice(start, source.indexOf('if (event.code === 4410)'))
    expect(branch).toContain('this.stopped = true')
    expect(branch).toContain('this.stopAudioGraph()')
    expect(branch).toContain('this.onSuperseded?.')
    expect(branch).toContain('return')
    // 报 incomplete 会把另一窗口正在录的那一路标成未完成；重连会与对方互抢。
    expect(branch).not.toContain('failIncomplete')
    expect(branch).not.toContain('scheduleReconnect')
  })
})
