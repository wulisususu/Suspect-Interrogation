import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SegmentUploader, buildSegmentRecordingWebSocketUrl, encodeSegmentFrame } from './browserSegmentRecorder'

class FakeSocket {
  readyState = 0
  binaryType: BinaryType = 'blob'
  sent: Array<string | ArrayBuffer> = []
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  send(data: string | ArrayBuffer) { this.sent.push(data) }
  close() { this.readyState = 3 }
  open() { this.readyState = 1; this.onopen?.(new Event('open')) }
  reply(message: object) { this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent) }
  drop(code = 1006) { this.readyState = 3; this.onclose?.({ code } as CloseEvent) }
  frames() {
    return this.sent.filter((item): item is ArrayBuffer => item instanceof ArrayBuffer).map((buffer) => {
      const view = new DataView(buffer)
      return { sequence: view.getUint32(0, true), start: Number(view.getBigUint64(4, true)), samples: (buffer.byteLength - 12) / 2 }
    })
  }
  controls() {
    return this.sent.filter((item): item is string => typeof item === 'string').map((item) => JSON.parse(item) as Record<string, unknown>)
  }
}

const half = (value = 1) => new Int16Array(8000).fill(value)

describe('segment recording uploader', () => {
  let sockets: FakeSocket[]
  let uploader: SegmentUploader

  beforeEach(() => {
    vi.useFakeTimers()
    sockets = []
    uploader = new SegmentUploader('wss://board/ws', () => {
      const socket = new FakeSocket()
      sockets.push(socket)
      return socket
    })
  })

  afterEach(() => {
    uploader.dispose()
    vi.useRealTimers()
  })

  it('derives wss from the https origin', () => {
    expect(buildSegmentRecordingWebSocketUrl('case 1', 'seg-1', 'https://192.168.2.109:18080'))
      .toBe('wss://192.168.2.109:18080/ws/recording/cases/case%201/segments/seg-1')
  })

  it('encodes the formal frame header', () => {
    const view = new DataView(encodeSegmentFrame(7, 16000, new Int16Array([1, -1])))
    expect([view.getUint32(0, true), Number(view.getBigUint64(4, true)), view.getInt16(12, true), view.getInt16(14, true)]).toEqual([7, 16000, 1, -1])
  })

  it('buffers audio until opened, rebases on the server cursor and replays unacked frames after a drop', () => {
    uploader.start()
    uploader.push(half())
    uploader.push(half())
    const first = sockets[0]!
    first.open()
    expect(first.controls()).toEqual([{ type: 'segment_open', fresh: true }])
    // 刷新页面后重开：服务端已录到 1.5 秒，本地帧接在其后
    first.reply({ type: 'segment_opened', status: 'RECORDING', clientSampleEnd: 24000, nextSequence: 4 })
    expect(first.frames()).toEqual([{ sequence: 4, start: 24000, samples: 8000 }, { sequence: 5, start: 32000, samples: 8000 }])
    first.reply({ type: 'ack', ackSequence: 4, durableSampleEnd: 32000 })
    expect(uploader.pendingFrames()).toBe(1)

    first.drop()
    uploader.push(half())
    vi.advanceTimersByTime(1000)
    const second = sockets[1]!
    second.open()
    expect(second.controls()).toEqual([{ type: 'segment_open', fresh: false }])
    second.reply({ type: 'segment_opened', status: 'RECORDING', clientSampleEnd: 32000, nextSequence: 5 })
    expect(second.frames()).toEqual([{ sequence: 5, start: 32000, samples: 8000 }, { sequence: 6, start: 40000, samples: 8000 }])
  })

  it('finalizes only after every frame is durable', async () => {
    uploader.start()
    const socket = sockets[0]!
    socket.open()
    socket.reply({ type: 'segment_opened', status: 'RECORDING', clientSampleEnd: 0, nextSequence: 1 })
    uploader.push(half())
    uploader.push(new Int16Array(100))
    const finished = uploader.finish()
    expect(socket.frames().map((frame) => frame.samples)).toEqual([8000, 100])
    expect(socket.controls().some((control) => control.type === 'segment_finalize')).toBe(false)
    socket.reply({ type: 'ack', ackSequence: 1, durableSampleEnd: 8000 })
    socket.reply({ type: 'ack', ackSequence: 2, durableSampleEnd: 8100 })
    expect(socket.controls().at(-1)).toEqual({ type: 'segment_finalize' })
    socket.reply({ type: 'segment_finalize_ack', status: 'COMPLETE' })
    await expect(finished).resolves.toBeUndefined()
  })

  it('stops quietly once the server says the segment is already saved', async () => {
    uploader.start()
    const socket = sockets[0]!
    socket.open()
    const finished = uploader.finish()
    socket.drop(4409)
    await expect(finished).resolves.toBeUndefined()
    vi.advanceTimersByTime(10_000)
    expect(sockets).toHaveLength(1)
  })
})
