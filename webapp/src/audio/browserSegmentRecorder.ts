import { runtimeConfig } from '../config/runtime'
import { Pcm16Resampler, browserVoiceprintCapability } from './browserVoiceprintCapture'

/**
 * 通道②全程录音：从「开始/继续询问」到「暂停/结束询问」麦克风一直开着，
 * 整段 16 kHz PCM16 推到后端，暂停时落成一个文件。
 *
 * 与通道①的按次采集互不干扰（各自打开麦克风）。网络断开时帧留在内存里，
 * 重连后补发；页面刷新后由新录音器从服务端记录的位置接着录，缺口由后端如实记录。
 */

const TARGET_SAMPLE_RATE = 16_000
const FRAME_SAMPLES = 8_000
/** 断网时最多在内存里留 10 分钟音频，再多就丢最早的帧（后端会记成缺口）。 */
const MAX_OUTBOX_SAMPLES = TARGET_SAMPLE_RATE * 600
const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 5_000]

export type SegmentRecorderState = 'idle' | 'recording' | 'reconnecting' | 'error'
export interface SegmentRecorderStatus {
  state: SegmentRecorderState
  segmentId: string | null
  error: string
}

interface OutboxFrame {
  localIndex: number
  localStart: number
  pcm: Int16Array
}

type SocketLike = Pick<WebSocket, 'readyState' | 'send' | 'close'> & {
  binaryType: BinaryType
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  onerror: ((event: Event) => void) | null
}

export function buildSegmentRecordingWebSocketUrl(caseId: string, segmentId: string, origin = runtimeConfig.apiBaseUrl) {
  const url = new URL(origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.search = ''
  url.hash = ''
  url.pathname = `/ws/recording/cases/${encodeURIComponent(caseId)}/segments/${encodeURIComponent(segmentId)}`
  return url.toString()
}

export function encodeSegmentFrame(sequence: number, startSample: number, pcm: Int16Array): ArrayBuffer {
  const buffer = new ArrayBuffer(12 + pcm.byteLength)
  const view = new DataView(buffer)
  view.setUint32(0, sequence, true)
  view.setBigUint64(4, BigInt(startSample), true)
  new Int16Array(buffer, 12).set(pcm)
  return buffer
}

/**
 * 帧的切分、缓存、补发与确认。样本位置先按本地计数，第一次连上后才知道
 * 服务端的起点（新段为 0，刷新页面后为已录到的位置），发送时再加上这个基准。
 */
export class SegmentUploader {
  private socket: SocketLike | null = null
  private opened = false
  private base: { sequence: number; sample: number } | null = null
  private outbox: OutboxFrame[] = []
  private outboxSamples = 0
  private partial: number[] = []
  private localSamples = 0
  private localFrames = 0
  private attempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined
  private finishing: { resolve: () => void; reject: (error: Error) => void } | null = null
  private closed = false
  onState: ((state: SegmentRecorderState, error?: string) => void) | null = null

  constructor(
    private readonly url: string,
    private readonly openSocket: (url: string) => SocketLike = (target) => new WebSocket(target),
  ) {}

  start() {
    this.connect()
  }

  push(pcm: Int16Array) {
    if (this.closed) return
    for (const sample of pcm) this.partial.push(sample)
    while (this.partial.length >= FRAME_SAMPLES) this.enqueue(Int16Array.from(this.partial.splice(0, FRAME_SAMPLES)))
  }

  /** 送完缓存并让后端落盘；超时就交给后端的收尾（文件照样保存，只是标记结尾未经浏览器确认）。 */
  finish(timeoutMs = 15_000): Promise<void> {
    if (this.partial.length) this.enqueue(Int16Array.from(this.partial.splice(0)))
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.finishing = null
        this.dispose()
        reject(new Error('全程录音尾音上传超时，已由服务端收尾保存'))
      }, timeoutMs)
      this.finishing = {
        resolve: () => { clearTimeout(timer); resolve() },
        reject: (error) => { clearTimeout(timer); reject(error) },
      }
      this.maybeFinalize()
    })
  }

  dispose() {
    this.closed = true
    clearTimeout(this.reconnectTimer)
    const socket = this.socket
    this.socket = null
    if (socket && socket.readyState <= 1) socket.close(1000, 'segment recorder stopped')
  }

  pendingFrames() {
    return this.outbox.length
  }

  private enqueue(pcm: Int16Array) {
    const frame = { localIndex: this.localFrames, localStart: this.localSamples, pcm }
    this.localFrames += 1
    this.localSamples += pcm.length
    this.outbox.push(frame)
    this.outboxSamples += pcm.length
    while (this.outboxSamples > MAX_OUTBOX_SAMPLES && this.outbox.length > 1) {
      this.outboxSamples -= this.outbox.shift()!.pcm.length
    }
    if (this.opened) this.send(frame)
  }

  private send(frame: OutboxFrame) {
    if (!this.socket || !this.base || this.socket.readyState !== 1) return
    this.socket.send(encodeSegmentFrame(this.base.sequence + frame.localIndex, this.base.sample + frame.localStart, frame.pcm))
  }

  private acknowledge(durableSampleEnd: number) {
    if (!this.base) return
    while (this.outbox.length && this.base.sample + this.outbox[0]!.localStart + this.outbox[0]!.pcm.length <= durableSampleEnd) {
      this.outboxSamples -= this.outbox.shift()!.pcm.length
    }
    this.maybeFinalize()
  }

  private maybeFinalize() {
    if (this.finishing && this.opened && !this.outbox.length && this.socket?.readyState === 1) {
      this.socket.send(JSON.stringify({ type: 'segment_finalize' }))
    }
  }

  private connect() {
    if (this.closed) return
    let socket: SocketLike
    try {
      socket = this.openSocket(this.url)
    } catch {
      this.scheduleReconnect()
      return
    }
    socket.binaryType = 'arraybuffer'
    this.socket = socket
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'segment_open', fresh: this.base === null }))
    }
    socket.onmessage = (event) => {
      if (typeof event.data !== 'string') return
      let message: Record<string, unknown>
      try {
        message = JSON.parse(event.data) as Record<string, unknown>
      } catch {
        return
      }
      if (message.type === 'segment_opened') {
        if (message.status !== 'RECORDING' && message.status !== 'CLOSING') return
        if (!this.base) this.base = { sequence: Number(message.nextSequence), sample: Number(message.clientSampleEnd) }
        this.opened = true
        this.attempts = 0
        this.onState?.('recording')
        this.acknowledge(Number(message.clientSampleEnd))
        for (const frame of this.outbox) this.send(frame)
        this.maybeFinalize()
      } else if (message.type === 'ack') {
        this.acknowledge(Number(message.durableSampleEnd))
      } else if (message.type === 'segment_finalize_ack') {
        const done = this.finishing
        this.finishing = null
        this.dispose()
        done?.resolve()
      }
    }
    socket.onclose = (event) => {
      if (this.socket !== socket) return
      this.socket = null
      this.opened = false
      if (this.closed) return
      if (event.code === 4409 || event.code === 4404) {
        // 段已保存（或不属于本案）：没什么可补的了。
        this.closed = true
        const done = this.finishing
        this.finishing = null
        done?.resolve()
        return
      }
      if (event.code === 4429) {
        this.closed = true
        this.onState?.('error', '另一个窗口正在录这段全程录音')
        this.finishing?.reject(new Error('另一个窗口正在录这段全程录音'))
        this.finishing = null
        return
      }
      this.scheduleReconnect()
    }
    socket.onerror = () => undefined
  }

  private scheduleReconnect() {
    if (this.closed) return
    this.onState?.('reconnecting')
    const delay = RECONNECT_DELAYS_MS[Math.min(this.attempts, RECONNECT_DELAYS_MS.length - 1)]!
    this.attempts += 1
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }
}

/** 麦克风 → 16 kHz PCM16 → 上传器。 */
class BrowserSegmentRecorder {
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private processor: ScriptProcessorNode | null = null
  private finishPromise: Promise<void> | null = null
  readonly uploader: SegmentUploader

  constructor(readonly caseId: string, readonly segmentId: string, onState: (state: SegmentRecorderState, error?: string) => void) {
    this.uploader = new SegmentUploader(buildSegmentRecordingWebSocketUrl(caseId, segmentId))
    this.uploader.onState = onState
  }

  async start() {
    this.uploader.start()
    const media = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      video: false,
    })
    if (this.finishPromise) {
      for (const track of media.getTracks()) track.stop()
      return
    }
    this.stream = media
    const context = new AudioContext()
    this.context = context
    if (context.state === 'suspended') await context.resume()
    const source = context.createMediaStreamSource(media)
    const processor = context.createScriptProcessor(4096, 1, 1)
    const mute = context.createGain()
    mute.gain.value = 0
    const resampler = new Pcm16Resampler(context.sampleRate, TARGET_SAMPLE_RATE)
    processor.onaudioprocess = (event) => {
      const pcm = resampler.process(event.inputBuffer.getChannelData(0))
      if (pcm.length) this.uploader.push(pcm)
    }
    source.connect(processor)
    processor.connect(mute)
    mute.connect(context.destination)
    this.processor = processor
  }

  finish() {
    if (!this.finishPromise) {
      if (this.processor) this.processor.onaudioprocess = null
      for (const track of this.stream?.getTracks() ?? []) track.stop()
      void this.context?.close().catch(() => undefined)
      this.finishPromise = this.uploader.finish()
    }
    return this.finishPromise
  }
}

let active: BrowserSegmentRecorder | null = null
let status: SegmentRecorderStatus = { state: 'idle', segmentId: null, error: '' }
const listeners = new Set<(status: SegmentRecorderStatus) => void>()

function publish(next: SegmentRecorderStatus) {
  status = next
  for (const listener of listeners) listener(status)
}

export function onSegmentRecorderStatus(listener: (status: SegmentRecorderStatus) => void) {
  listeners.add(listener)
  listener(status)
  return () => { listeners.delete(listener) }
}

/** 让麦克风跟随当前询问段：有段就录这一段，没有（暂停/结束）就收尾。 */
export function syncSegmentRecorder(caseId: string, segmentId: string | null) {
  if (active && active.caseId === caseId && active.segmentId === segmentId) return
  if (active) void finishSegmentRecorder().catch(() => undefined)
  if (!segmentId) return
  const capability = browserVoiceprintCapability()
  if (!capability.available) {
    publish({ state: 'error', segmentId, error: capability.reason })
    return
  }
  const recorder = new BrowserSegmentRecorder(caseId, segmentId, (state, error = '') => {
    if (active === recorder) publish({ state, segmentId, error })
  })
  active = recorder
  publish({ state: 'reconnecting', segmentId, error: '' })
  recorder.start().catch((error: unknown) => {
    if (active !== recorder) return
    publish({ state: 'error', segmentId, error: error instanceof Error ? error.message : '麦克风无法打开' })
  })
}

/** 暂停/结束询问后调用：停麦克风、送完尾音、等后端把这一段落成文件。 */
export async function finishSegmentRecorder() {
  const recorder = active
  if (!recorder) return
  active = null
  publish({ state: 'idle', segmentId: null, error: '' })
  await recorder.finish()
}
