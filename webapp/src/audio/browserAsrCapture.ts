import { runtimeConfig } from '../config/runtime'
import {
  Pcm16Resampler,
  browserVoiceprintCapability,
} from './browserVoiceprintCapture'

const TARGET_SAMPLE_RATE = 16_000

type CaptureKind = 'FORMAL' | 'QUESTION_PREP'
type BrowserAudioLevelSample = { sampleCount: number; sampleRate: number; rms: number; peak: number }

export interface BrowserFormalAudioFrame {
  sequence: number
  startSample: bigint
  pcm: Uint8Array
}

export interface BrowserFormalAudioFrameStore {
  list(): Promise<BrowserFormalAudioFrame[]>
  put(frame: BrowserFormalAudioFrame): Promise<void>
  delete(sequence: number): Promise<void>
  clear(): Promise<void>
  loadProgress?(): Promise<{ nextSequence: number; nextStartSample: bigint } | null>
  saveProgress?(nextSequence: number, nextStartSample: bigint): Promise<void>
}

export class BrowserFormalCaptureLeaseError extends Error {
  constructor(readonly captureKey: string, readonly reason: 'CONFLICT' | 'UNSUPPORTED') {
    super(reason === 'CONFLICT'
      ? '此正式录音正在另一个标签页中采集，请在拥有录音的标签页操作'
      : '当前浏览器不支持跨标签页录音锁，无法安全恢复此正式录音')
    this.name = 'BrowserFormalCaptureLeaseError'
  }
}

export class BrowserFormalCaptureLease {
  private released = false

  constructor(
    private readonly releaseLock: () => void,
    readonly completion: Promise<void>,
  ) {}

  release() {
    if (this.released) return
    this.released = true
    this.releaseLock()
  }
}

export function takeMatchingBrowserFormalFinalization<T extends { captureKey: string }>(
  pending: T | null,
  captureKey: string | undefined,
) {
  if (pending && captureKey !== undefined && pending.captureKey === captureKey) {
    return { resumed: pending, remaining: null }
  }
  return { resumed: null, remaining: pending }
}

export async function acquireBrowserFormalCaptureLease(captureKey: string) {
  const lockManager = typeof navigator === 'undefined' ? undefined : navigator.locks
  if (!lockManager) throw new BrowserFormalCaptureLeaseError(captureKey, 'UNSUPPORTED')

  let resolveAcquired!: (lock: Lock | null) => void
  let rejectAcquired!: (error: unknown) => void
  const acquired = new Promise<Lock | null>((resolve, reject) => {
    resolveAcquired = resolve
    rejectAcquired = reject
  })
  let releaseLock!: () => void
  const held = new Promise<void>((resolve) => { releaseLock = resolve })
  const completion = Promise.resolve(lockManager.request(
    `suspect-interrogation:formal-audio:${captureKey}`,
    { mode: 'exclusive', ifAvailable: true },
    async (lock) => {
      resolveAcquired(lock)
      if (lock) await held
    },
  )).then(() => undefined).catch(() => {
    rejectAcquired(new BrowserFormalCaptureLeaseError(captureKey, 'UNSUPPORTED'))
  })
  const lock = await acquired
  if (!lock) {
    await completion
    throw new BrowserFormalCaptureLeaseError(captureKey, 'CONFLICT')
  }
  return new BrowserFormalCaptureLease(releaseLock, completion)
}

export function reconcileBrowserFormalCursor(
  progress: { nextSequence: number; nextStartSample: bigint } | null,
  pending: BrowserFormalAudioFrame[],
) {
  const saved = progress ?? { nextSequence: 1, nextStartSample: 0n }
  const latest = pending.reduce<BrowserFormalAudioFrame | null>(
    (current, frame) => !current || frame.sequence > current.sequence ? frame : current,
    null,
  )
  if (!latest) return saved

  const pendingCursor = {
    nextSequence: latest.sequence + 1,
    nextStartSample: latest.startSample + BigInt(latest.pcm.byteLength / 2),
  }
  if (pendingCursor.nextSequence > saved.nextSequence) return pendingCursor
  if (pendingCursor.nextSequence < saved.nextSequence) return saved
  if (pendingCursor.nextStartSample !== saved.nextStartSample) {
    throw new Error('formal audio cursor conflicts with persisted outbox frames')
  }
  return saved
}

export class BoundedBrowserAsrOutbox {
  constructor(
    private readonly store: BrowserFormalAudioFrameStore,
    private readonly maxBytes: number,
  ) {}

  async list() {
    return (await this.store.list()).sort((left, right) => left.sequence - right.sequence)
  }

  async append(frame: BrowserFormalAudioFrame) {
    if (!Number.isInteger(frame.sequence) || frame.sequence < 1 || frame.pcm.byteLength === 0 || frame.pcm.byteLength % 2) {
      throw new Error('formal audio frame is invalid')
    }
    const existing = await this.store.list()
    const prior = existing.find((item) => item.sequence === frame.sequence)
    if (prior) {
      if (prior.startSample !== frame.startSample || !sameBytes(prior.pcm, frame.pcm)) {
        throw new Error('formal audio sequence was reused with different data')
      }
      return
    }
    const queuedBytes = existing.reduce((total, item) => total + item.pcm.byteLength, 0)
    if (queuedBytes + frame.pcm.byteLength > this.maxBytes) {
      throw new Error('formal audio outbox capacity is exhausted')
    }
    await this.store.put(frame)
  }

  acknowledge(sequence: number) {
    return this.store.delete(sequence)
  }

  clear() {
    return this.store.clear()
  }

  loadProgress() {
    return this.store.loadProgress?.() ?? Promise.resolve(null)
  }

  saveProgress(nextSequence: number, nextStartSample: bigint) {
    return this.store.saveProgress?.(nextSequence, nextStartSample) ?? Promise.resolve()
  }
}

const OUTBOX_DB_NAME = 'suspect-interrogation-browser-asr'
const OUTBOX_STORE_NAME = 'formal-audio-frames'
const OUTBOX_CURSOR_STORE_NAME = 'formal-audio-cursors'
const MAX_FORMAL_OUTBOX_BYTES = 16 * 1024 * 1024
const FORMAL_HEADER_BYTES = 12
const MAX_FORMAL_FRAME_BYTES = 32_000
const FORMAL_ACK_TIMEOUT_MS = 5_000

interface StoredBrowserFormalAudioFrame extends BrowserFormalAudioFrame {
  key: string
  captureKey: string
}

export interface RecoverableBrowserFormalCapture {
  captureId: string
  pendingFrameCount: number
  pendingBytes: number
}

let outboxDatabase: Promise<IDBDatabase> | null = null

function openOutboxDatabase() {
  if (!outboxDatabase) {
    outboxDatabase = new Promise<IDBDatabase>((resolve, reject) => {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('当前浏览器不支持持久化录音缓存'))
        return
      }
      const request = indexedDB.open(OUTBOX_DB_NAME, 2)
      request.onupgradeneeded = () => {
        const database = request.result
        if (!database.objectStoreNames.contains(OUTBOX_STORE_NAME)) {
          const store = database.createObjectStore(OUTBOX_STORE_NAME, { keyPath: 'key' })
          store.createIndex('captureKey', 'captureKey', { unique: false })
        }
        if (!database.objectStoreNames.contains(OUTBOX_CURSOR_STORE_NAME)) {
          database.createObjectStore(OUTBOX_CURSOR_STORE_NAME, { keyPath: 'captureKey' })
        }
      }
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error || new Error('无法打开浏览器录音缓存'))
      request.onblocked = () => reject(new Error('浏览器录音缓存仍被其他页面占用'))
    }).catch((error) => {
      outboxDatabase = null
      throw error
    })
  }
  return outboxDatabase
}

function requestValue<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('浏览器录音缓存读写失败'))
  })
}

class IndexedDbBrowserFormalAudioFrameStore implements BrowserFormalAudioFrameStore {
  constructor(private readonly captureKey: string) {}

  private async inCaptureStore<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => Promise<T>) {
    return this.inStore(OUTBOX_STORE_NAME, mode, action)
  }

  private async inStore<T>(
    storeName: string,
    mode: IDBTransactionMode,
    action: (store: IDBObjectStore) => Promise<T>,
  ) {
    const database = await openOutboxDatabase()
    const transaction = database.transaction(storeName, mode)
    const completed = mode === 'readwrite'
      ? new Promise<void>((resolve, reject) => {
        transaction.oncomplete = () => resolve()
        transaction.onabort = () => reject(transaction.error || new Error('浏览器录音缓存写入失败'))
        transaction.onerror = () => reject(transaction.error || new Error('浏览器录音缓存写入失败'))
      })
      : Promise.resolve()
    const result = await action(transaction.objectStore(storeName))
    await completed
    return result
  }

  list() {
    return this.inCaptureStore('readonly', async (store) => {
      const rows = await requestValue(store.index('captureKey').getAll(this.captureKey)) as StoredBrowserFormalAudioFrame[]
      return rows.map(({ sequence, startSample, pcm }) => ({
        sequence,
        startSample: BigInt(startSample),
        pcm: new Uint8Array(pcm),
      }))
    })
  }

  put(frame: BrowserFormalAudioFrame) {
    return this.inCaptureStore('readwrite', async (store) => {
      const record: StoredBrowserFormalAudioFrame = {
        key: `${this.captureKey}:${frame.sequence}`,
        captureKey: this.captureKey,
        sequence: frame.sequence,
        startSample: frame.startSample,
        pcm: new Uint8Array(frame.pcm),
      }
      await requestValue(store.put(record))
    }).then(() => undefined)
  }

  delete(sequence: number) {
    return this.inCaptureStore('readwrite', async (store) => {
      await requestValue(store.delete(`${this.captureKey}:${sequence}`))
    }).then(() => undefined)
  }

  clear() {
    return this.inCaptureStore('readwrite', async (store) => {
      const keys = await requestValue(store.index('captureKey').getAllKeys(this.captureKey))
      for (const key of keys) store.delete(key)
    }).then(() => this.inStore(OUTBOX_CURSOR_STORE_NAME, 'readwrite', async (store) => {
      await requestValue(store.delete(this.captureKey))
    })).then(() => undefined)
  }

  loadProgress() {
    return this.inStore(OUTBOX_CURSOR_STORE_NAME, 'readonly', async (store) => {
      const record = await requestValue(store.get(this.captureKey)) as
        | { nextSequence: number; nextStartSample: string }
        | undefined
      return record
        ? { nextSequence: Number(record.nextSequence), nextStartSample: BigInt(record.nextStartSample) }
        : null
    })
  }

  saveProgress(nextSequence: number, nextStartSample: bigint) {
    return this.inStore(OUTBOX_CURSOR_STORE_NAME, 'readwrite', async (store) => {
      await requestValue(store.put({
        captureKey: this.captureKey,
        nextSequence,
        nextStartSample: nextStartSample.toString(),
      }))
    }).then(() => undefined)
  }
}

function sameBytes(left: Uint8Array, right: Uint8Array) {
  return left.byteLength === right.byteLength && left.every((value, index) => value === right[index])
}

export async function listRecoverableBrowserFormalCaptures(caseId: string): Promise<RecoverableBrowserFormalCapture[]> {
  const database = await openOutboxDatabase()
  const transaction = database.transaction(OUTBOX_STORE_NAME, 'readonly')
  const rows = await requestValue(transaction.objectStore(OUTBOX_STORE_NAME).getAll()) as StoredBrowserFormalAudioFrame[]
  const prefix = `${caseId}:`
  const grouped = new Map<string, StoredBrowserFormalAudioFrame[]>()
  for (const row of rows) {
    if (!row.captureKey.startsWith(prefix)) continue
    const pending = grouped.get(row.captureKey) ?? []
    pending.push(row)
    grouped.set(row.captureKey, pending)
  }
  return [...grouped.entries()]
    .map(([captureKey, pending]) => ({
      captureId: captureKey.slice(prefix.length),
      pendingFrameCount: pending.length,
      pendingBytes: pending.reduce((total, frame) => total + frame.pcm.byteLength, 0),
    }))
    .sort((left, right) => left.captureId.localeCompare(right.captureId))
}

function openRecoverySocket(url: string) {
  return new Promise<WebSocket>((resolve, reject) => {
    const socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'
    const timer = window.setTimeout(() => {
      socket.close()
      reject(new Error('连接录音恢复通道超时'))
    }, 10_000)
    socket.addEventListener('open', () => {
      window.clearTimeout(timer)
      resolve(socket)
    }, { once: true })
    socket.addEventListener('error', () => {
      window.clearTimeout(timer)
      reject(new Error('无法连接录音恢复通道'))
    }, { once: true })
  })
}

function sendRecoveryMessage(socket: WebSocket, data: ArrayBuffer | string) {
  return new Promise<Record<string, unknown>>((resolve, reject) => {
    const timer = window.setTimeout(() => finish(() => reject(new Error('等待服务端录音确认超时'))), 10_000)
    const cleanup = () => {
      window.clearTimeout(timer)
      socket.removeEventListener('message', onMessage)
      socket.removeEventListener('close', onClose)
      socket.removeEventListener('error', onError)
    }
    const finish = (callback: () => void) => {
      cleanup()
      callback()
    }
    const onMessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') {
        finish(() => reject(new Error('服务端录音确认格式无效')))
        return
      }
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>
        if (payload.type === 'capture_incomplete_ack') {
          finish(() => reject(new Error('服务端仍将录音标记为不完整')))
          return
        }
        finish(() => resolve(payload))
      } catch {
        finish(() => reject(new Error('服务端录音确认格式无效')))
      }
    }
    const onClose = () => finish(() => reject(new Error('录音恢复通道已断开')))
    const onError = () => finish(() => reject(new Error('录音恢复通道连接异常')))
    socket.addEventListener('message', onMessage, { once: true })
    socket.addEventListener('close', onClose, { once: true })
    socket.addEventListener('error', onError, { once: true })
    try {
      if (socket.readyState !== WebSocket.OPEN) throw new Error('录音恢复通道未连接')
      socket.send(data)
    } catch (error) {
      finish(() => reject(error))
    }
  })
}

export async function recoverBrowserFormalCapture(
  caseId: string,
  captureId: string,
  origin = runtimeConfig.apiBaseUrl,
) {
  const captureKey = `${caseId}:${captureId}`
  const lease = await acquireBrowserFormalCaptureLease(captureKey)
  const outbox = new BoundedBrowserAsrOutbox(
    new IndexedDbBrowserFormalAudioFrameStore(captureKey),
    MAX_FORMAL_OUTBOX_BYTES,
  )
  let socket: WebSocket | null = null
  try {
    const pending = await outbox.list()
    if (!pending.length) throw new Error('本机没有待补录的音频分片')
    const cursor = reconcileBrowserFormalCursor(await outbox.loadProgress(), pending)
    socket = await openRecoverySocket(buildBrowserAsrCaptureWebSocketUrl(caseId, captureId, origin))
    for (const frame of pending) {
      const ack = await sendRecoveryMessage(
        socket,
        encodeBrowserFormalAsrFrame(frame.sequence, frame.startSample, frame.pcm),
      )
      const expectedEnd = frame.startSample + BigInt(frame.pcm.byteLength / 2)
      const acknowledgedEnd = Number(ack.durableSampleEnd)
      if (ack.type !== undefined || Number(ack.ackSequence) !== frame.sequence
          || !Number.isSafeInteger(acknowledgedEnd) || BigInt(acknowledgedEnd) !== expectedEnd) {
        throw new Error('服务端录音确认与本机分片不一致')
      }
      await outbox.acknowledge(frame.sequence)
    }
    const nextSample = Number(cursor.nextStartSample)
    if (!Number.isSafeInteger(nextSample)) throw new Error('本机录音采样位置超出可恢复范围')
    const completion = await sendRecoveryMessage(socket, JSON.stringify({
      type: 'capture_recovery_complete',
      nextSequence: cursor.nextSequence,
      nextSample,
    }))
    if (completion.type !== 'capture_recovery_complete_ack' || completion.captureId !== captureId) {
      throw new Error('服务端未确认录音恢复完成')
    }
    await outbox.clear()
    return completion
  } finally {
    socket?.close()
    lease.release()
    await lease.completion
  }
}

export function encodeBrowserFormalAsrFrame(
  sequence: number,
  startSample: bigint,
  pcm: Uint8Array,
) {
  if (!Number.isInteger(sequence) || sequence < 1 || sequence > 0xffff_ffff) {
    throw new Error('formal audio sequence is outside uint32 range')
  }
  if (startSample < 0n || startSample > 0xffff_ffff_ffff_ffffn) {
    throw new Error('formal audio sample start is outside uint64 range')
  }
  if (pcm.byteLength === 0 || pcm.byteLength % 2) {
    throw new Error('formal audio payload must be non-empty PCM16')
  }
  const output = new ArrayBuffer(FORMAL_HEADER_BYTES + pcm.byteLength)
  const header = new DataView(output)
  header.setUint32(0, sequence, true)
  header.setBigUint64(4, startSample, true)
  new Uint8Array(output, FORMAL_HEADER_BYTES).set(pcm)
  return output
}

export async function sendNextBrowserFormalFrame(
  socket: { readyState: number; send(data: ArrayBuffer): void },
  outbox: Pick<BoundedBrowserAsrOutbox, 'list'>,
) {
  if (socket.readyState !== 1) return null
  const frame = (await outbox.list()).sort((left, right) => left.sequence - right.sequence)[0]
  if (!frame) return null
  socket.send(encodeBrowserFormalAsrFrame(frame.sequence, frame.startSample, frame.pcm))
  return frame
}

export class BrowserFormalIncompleteMarker {
  private sentOnSocket = false
  private acknowledged = false

  get confirmed() {
    return this.acknowledged
  }

  shouldSend(options: {
    failed: boolean
    reason: string | null
    pendingCount: number
    mayBypassPending?: boolean
  }) {
    return (
      options.failed
      && Boolean(options.reason)
      && !this.sentOnSocket
      && !this.acknowledged
      && (options.pendingCount === 0 || options.mayBypassPending === true)
    )
  }

  markSent() {
    this.sentOnSocket = true
  }

  confirm() {
    this.acknowledged = true
  }

  onSocketClosed() {
    if (!this.acknowledged) this.sentOnSocket = false
  }
}

export async function removeBrowserFormalFrameAfterDurableAck(
  outbox: Pick<BoundedBrowserAsrOutbox, 'acknowledge'>,
  sequence: number,
  onLocalDeleteFailure: (error: unknown) => void,
) {
  try {
    await outbox.acknowledge(sequence)
    return true
  } catch (error) {
    onLocalDeleteFailure(error)
    return false
  }
}

export async function waitForBrowserFormalOutboxDrain(
  outbox: Pick<BoundedBrowserAsrOutbox, 'list'>,
  pump: () => Promise<void>,
  timeoutMs: number,
  mayStopWithIncompleteOutbox: () => boolean = () => false,
) {
  const deadline = Date.now() + timeoutMs
  while (true) {
    if (mayStopWithIncompleteOutbox()) return true
    if (!(await outbox.list()).length) return true
    if (Date.now() >= deadline) return false
    await pump()
    await new Promise<void>((resolve) => setTimeout(resolve, 10))
  }
}

export async function confirmBrowserFormalOutboxFinalization(
  outbox: Pick<BoundedBrowserAsrOutbox, 'list' | 'clear'>,
  preserveUnacknowledged: boolean,
) {
  if (preserveUnacknowledged) return
  if ((await outbox.list()).length) {
    throw new Error('服务器已结束录音，但仍有未确认音频；浏览器缓存已保留且录音标记为不完整')
  }
  await outbox.clear()
}

function wsOrigin(origin: string) {
  const url = new URL(origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.search = ''
  url.hash = ''
  return url
}

export function buildBrowserAsrCaptureWebSocketUrl(
  caseId: string,
  captureId: string,
  origin = runtimeConfig.apiBaseUrl,
) {
  const url = wsOrigin(origin)
  url.pathname = `/ws/asr/cases/${encodeURIComponent(caseId)}/capture/${encodeURIComponent(captureId)}`
  return url.toString().replace(/\/$/, '')
}

export function buildBrowserQuestionPreparationWebSocketUrl(
  caseId: string,
  captureId: string,
  origin = runtimeConfig.apiBaseUrl,
) {
  const url = wsOrigin(origin)
  url.pathname = `/ws/asr/cases/${encodeURIComponent(caseId)}/question-preparation/${encodeURIComponent(captureId)}`
  return url.toString().replace(/\/$/, '')
}

class BrowserPcmStreamer {
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private analyser: AnalyserNode | null = null
  private processor: ScriptProcessorNode | null = null
  private mute: GainNode | null = null
  private waveformTimer: number | undefined
  private socket: WebSocket | null = null
  private pendingSocket: WebSocket | null = null
  private stopped = false
  private stopRequested = false
  private stopInProgress: Promise<void> | null = null
  private cancelStartup: () => void = () => undefined
  private readonly startupCancelled = new Promise<void>((resolve) => { this.cancelStartup = resolve })
  private failed = false
  private microphoneStopped = false
  private drainFailureReported = false
  private kind: CaptureKind = 'QUESTION_PREP'
  private url = ''
  private outbox: BoundedBrowserAsrOutbox | null = null
  private nextSequence = 1
  private nextStartSample = 0n
  private frameWrites: Promise<void> = Promise.resolve()
  private pumping: Promise<void> | null = null
  private inFlightSequence: number | null = null
  private reconnectTimer: number | undefined
  private formalAckTimer: number | undefined
  private failureReason: string | null = null
  private incompleteMarker = new BrowserFormalIncompleteMarker()
  private incompleteMarkerMayBypassOutbox = false
  private captureLease: BrowserFormalCaptureLease | null = null
  onAudioLevel: ((sample: BrowserAudioLevelSample) => void) | null = null
  onUnexpectedClose: (() => void) | null = null
  onIncomplete: ((message: string) => void) | null = null
  onSuperseded: ((reason: string) => void) | null = null

  async start(url: string, kind: CaptureKind, captureKey?: string, captureLease?: BrowserFormalCaptureLease) {
    this.kind = kind
    this.url = url
    this.captureLease = captureLease ?? null
    let formalOutboxScanned = false
    try {
      if (kind === 'FORMAL') {
        const store = new IndexedDbBrowserFormalAudioFrameStore(String(captureKey || 'unknown-capture'))
        this.outbox = new BoundedBrowserAsrOutbox(store, MAX_FORMAL_OUTBOX_BYTES)
        const pending = await this.outbox.list()
        formalOutboxScanned = true
        const progress = await this.outbox.loadProgress()
        const cursor = reconcileBrowserFormalCursor(progress, pending)
        this.nextSequence = cursor.nextSequence
        this.nextStartSample = cursor.nextStartSample
        await this.outbox.saveProgress(this.nextSequence, this.nextStartSample)
      }

      if (this.stopRequested || this.stopped) throw new Error('浏览器麦克风采集已取消')
      const socket = await this.waitForStartup(this.openSocket(url))
      if (this.stopRequested || this.stopped) {
        socket.close(1000, 'capture stopped')
        throw new Error('浏览器麦克风采集已取消')
      }
      this.bindSocket(socket)
      if (this.outbox) await this.pumpFormalOutbox()
      if (this.stopRequested || this.stopped) throw new Error('浏览器麦克风采集已取消')

      const capability = browserVoiceprintCapability()
      if (!capability.available) {
        if (this.kind === 'FORMAL') this.failIncomplete(`浏览器音频不可用：${capability.reason}`)
        throw new Error(capability.reason)
      }

      const media = await this.waitForStartup(navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
        video: false,
      }).then((resolved) => {
        if (this.stopRequested || this.stopped) {
          for (const track of resolved.getTracks()) track.stop()
          throw new Error('浏览器麦克风采集已取消')
        }
        return resolved
      }))
      if (this.stopRequested || this.stopped) {
        for (const track of media.getTracks()) track.stop()
        throw new Error('浏览器麦克风采集已取消')
      }
      this.stream = media

      const context = new AudioContext()
      this.context = context
      if (context.state === 'suspended') await context.resume()
      if (this.stopRequested || this.stopped) throw new Error('浏览器麦克风采集已取消')
      const source = context.createMediaStreamSource(media)
      const analyser = context.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0
      const processor = context.createScriptProcessor(4096, 1, 1)
      const mute = context.createGain()
      mute.gain.value = 0
      const resampler = new Pcm16Resampler(context.sampleRate, TARGET_SAMPLE_RATE)
      const waveformPcm = new Float32Array(analyser.fftSize)
      let waveformSampleCount = 0
      const waveformStartedAt = performance.now()

      processor.onaudioprocess = (event) => {
        if (this.stopped || this.failed) return
        const pcm = resampler.process(event.inputBuffer.getChannelData(0))
        if (!pcm.length) return
        const bytes = new Uint8Array(pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength))
        if (this.kind === 'FORMAL') this.persistFormalPcm(bytes)
        else {
          const activeSocket = this.socket
          if (activeSocket?.readyState === WebSocket.OPEN) activeSocket.send(bytes.buffer)
        }
      }

      source.connect(analyser)
      analyser.connect(processor)
      processor.connect(mute)
      mute.connect(context.destination)
      this.source = source
      this.analyser = analyser
      this.processor = processor
      this.mute = mute
      this.waveformTimer = window.setInterval(() => {
        if (this.stopped || this.failed || !this.analyser || context.state !== 'running') return
        this.analyser.getFloatTimeDomainData(waveformPcm)
        let sumSquares = 0
        let peak = 0
        for (const value of waveformPcm) {
          const magnitude = Math.min(1, Math.abs(value))
          sumSquares += magnitude * magnitude
          if (magnitude > peak) peak = magnitude
        }
        waveformSampleCount = Math.round((performance.now() - waveformStartedAt) * context.sampleRate / 1000)
        this.onAudioLevel?.({
          sampleCount: waveformSampleCount,
          sampleRate: context.sampleRate,
          rms: Math.sqrt(sumSquares / waveformPcm.length) * 32768,
          peak: peak * 32768,
        })
      }, 40)
    } catch (error) {
      if (this.kind === 'FORMAL' && !this.stopRequested) {
        const detail = error instanceof Error ? error.message : String(error)
        this.failIncomplete(`浏览器音频恢复失败：${detail}`, !formalOutboxScanned)
      }
      await this.stop()
      throw error
    }
  }

  private openSocket(url: string): Promise<WebSocket> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url)
      this.pendingSocket = socket
      socket.binaryType = 'arraybuffer'
      let settled = false
      const finish = (callback: () => void) => {
        if (settled) return
        settled = true
        window.clearTimeout(timer)
        if (this.pendingSocket === socket) this.pendingSocket = null
        callback()
      }
      const timer = window.setTimeout(() => {
        socket.close()
        finish(() => reject(new Error('连接 Linux 局域网音频通道超时')))
      }, 10_000)
      socket.onopen = () => finish(() => resolve(socket))
      socket.onerror = () => finish(() => reject(new Error('无法连接 Linux 局域网音频通道；请确认后端已启用 BROWSER 测试音源')))
      socket.onclose = () => finish(() => reject(new Error('浏览器音频通道在连接完成前关闭')))
    })
  }

  private async waitForStartup<T>(operation: Promise<T>): Promise<T> {
    const result = await Promise.race([
      operation.then((value) => ({ cancelled: false as const, value })),
      this.startupCancelled.then(() => ({ cancelled: true as const })),
    ])
    if (result.cancelled) throw new Error('浏览器麦克风采集已取消')
    return result.value
  }

  private bindSocket(socket: WebSocket) {
    this.socket = socket
    socket.binaryType = 'arraybuffer'
    socket.onmessage = (event) => {
      if (this.socket === socket && this.kind === 'FORMAL') void this.handleFormalAck(event.data)
    }
    socket.onclose = (event) => {
      if (this.socket !== socket) return
      this.socket = null
      this.inFlightSequence = null
      this.clearFormalAckTimer()
      this.incompleteMarker.onSocketClosed()
      if (this.stopped) return
      if (event.code === 4429) {
        // 另一路连接已经占用这路采集。停止本页但不报 incomplete：否则会把
        // 正在录音的那一路标成未完成，也不自动重连，避免两页互抢。
        this.stopped = true
        this.stopAudioGraph()
        this.captureLease?.release()
        this.onSuperseded?.(event.reason || '同一路采集已有其它连接在录音')
        return
      }
      if (event.code === 4410) {
        this.failIncomplete(event.reason || '服务器检测到音频不连续')
      }
      if (this.incompleteMarker.confirmed) return
      if (this.kind === 'FORMAL') this.scheduleReconnect()
      else this.onUnexpectedClose?.()
    }
  }

  private persistFormalPcm(pcm: Uint8Array) {
    this.frameWrites = this.frameWrites.then(async () => {
      if (this.failed || this.stopped || !this.outbox) return
      for (let offset = 0; offset < pcm.byteLength; offset += MAX_FORMAL_FRAME_BYTES) {
        const chunk = pcm.slice(offset, Math.min(pcm.byteLength, offset + MAX_FORMAL_FRAME_BYTES))
        const frame: BrowserFormalAudioFrame = {
          sequence: this.nextSequence,
          startSample: this.nextStartSample,
          pcm: chunk,
        }
        await this.outbox.append(frame)
        this.nextSequence += 1
        this.nextStartSample += BigInt(chunk.byteLength / 2)
        await this.outbox.saveProgress(this.nextSequence, this.nextStartSample)
        await this.pumpFormalOutbox()
      }
    }).catch((error) => {
      this.failIncomplete(error instanceof Error ? error.message : String(error))
    })
  }

  private async handleFormalAck(data: unknown) {
    try {
      if (typeof data !== 'string') throw new Error('durable audio acknowledgement is not JSON')
      const payload = JSON.parse(data) as {
        type?: unknown
        ackSequence?: unknown
        durableSampleEnd?: unknown
      }
      if (payload.type === 'capture_incomplete_ack') {
        this.incompleteMarker.confirm()
        this.failIncomplete('服务器已将录音标记为不完整')
        return
      }
      const sequence = Number(payload.ackSequence)
      const durableEnd = Number(payload.durableSampleEnd)
      if (!Number.isSafeInteger(sequence) || !Number.isSafeInteger(durableEnd)) {
        throw new Error('durable audio acknowledgement is invalid')
      }
      const pending = await this.outbox?.list() ?? []
      const frame = pending.find((item) => item.sequence === sequence)
      if (!frame) {
        if (sequence < this.nextSequence) return
        throw new Error('durable audio acknowledgement does not match the outbox')
      }
      const expectedEnd = frame.startSample + BigInt(frame.pcm.byteLength / 2)
      if (BigInt(durableEnd) !== expectedEnd) throw new Error('durable audio acknowledgement sample range mismatched')
      if (this.inFlightSequence === sequence) this.clearFormalAckTimer()
      const outbox = this.outbox
      if (!outbox) throw new Error('durable audio outbox is unavailable')
      const removed = await removeBrowserFormalFrameAfterDurableAck(
        outbox,
        sequence,
        (error) => {
          if (this.inFlightSequence === sequence) this.inFlightSequence = null
          const detail = error instanceof Error ? error.message : String(error)
          this.failIncomplete(`服务器已确认音频，但本地缓存删除失败，原帧已保留：${detail}`, true)
        },
      )
      if (!removed) return
      if (this.inFlightSequence === sequence) this.inFlightSequence = null
      await this.pumpFormalOutbox()
    } catch (error) {
      this.failIncomplete(error instanceof Error ? error.message : String(error))
    }
  }

  private async pumpFormalOutbox() {
    if (this.pumping) return this.pumping
    this.pumping = (async () => {
      if (
        this.stopped
        || this.incompleteMarker.confirmed
        || this.inFlightSequence !== null
        || !this.socket
      ) return
      if (!this.outbox && !(this.failed && this.incompleteMarkerMayBypassOutbox)) return
      let pending: BrowserFormalAudioFrame[] = []
      if (this.outbox) {
        try {
          pending = await this.outbox.list()
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error)
          this.failIncomplete(`浏览器录音缓存无法读取：${detail}`, true)
          pending = []
        }
      }
      if (this.incompleteMarker.shouldSend({
        failed: this.failed,
        reason: this.failureReason,
        pendingCount: pending.length,
        mayBypassPending: this.incompleteMarkerMayBypassOutbox,
      }) && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'capture_incomplete', reason: this.failureReason }))
        this.incompleteMarker.markSent()
        return
      }
      if (!pending.length) {
        return
      }
      const frame = await sendNextBrowserFormalFrame(this.socket, { list: async () => pending })
      if (frame) {
        this.inFlightSequence = frame.sequence
        const socket = this.socket
        if (socket?.readyState === WebSocket.OPEN) {
          this.formalAckTimer = window.setTimeout(() => {
            this.formalAckTimer = undefined
            if (this.socket === socket && this.inFlightSequence === frame.sequence) {
              socket.close(4000, 'durable audio acknowledgement timed out')
            }
          }, FORMAL_ACK_TIMEOUT_MS)
        }
      }
    })().finally(() => { this.pumping = null })
    return this.pumping
  }

  private clearFormalAckTimer() {
    if (this.formalAckTimer !== undefined) window.clearTimeout(this.formalAckTimer)
    this.formalAckTimer = undefined
  }

  private scheduleReconnect() {
    if (this.reconnectTimer !== undefined || this.stopped) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = undefined
      void this.reconnect()
    }, 500)
  }

  private async reconnect() {
    if (this.stopped) return
    try {
      const socket = await this.openSocket(this.url)
      if (this.stopped) {
        socket.close(1000, 'capture stopped')
        return
      }
      this.bindSocket(socket)
      await this.pumpFormalOutbox()
    } catch {
      this.scheduleReconnect()
    }
  }

  private failIncomplete(message: string, mayBypassPending = false) {
    if (this.stopped) return
    if (mayBypassPending) this.incompleteMarkerMayBypassOutbox = true
    if (this.failed) {
      if (this.incompleteMarker.confirmed) return
      if (this.socket) void this.pumpFormalOutbox()
      else this.scheduleReconnect()
      return
    }
    this.failed = true
    this.failureReason = message
    this.stopAudioGraph()
    if (!this.socket) this.scheduleReconnect()
    else void this.pumpFormalOutbox()
    this.onIncomplete?.(`录音缓存不可用或已满：${message}`)
  }

  private stopAudioGraph() {
    if (this.waveformTimer !== undefined) window.clearInterval(this.waveformTimer)
    this.waveformTimer = undefined
    if (this.processor) this.processor.onaudioprocess = null
    try { this.source?.disconnect() } catch { /* noop */ }
    try { this.analyser?.disconnect() } catch { /* noop */ }
    try { this.processor?.disconnect() } catch { /* noop */ }
    try { this.mute?.disconnect() } catch { /* noop */ }
    for (const track of this.stream?.getTracks() ?? []) track.stop()
  }

  formalOutboxForFinalization() {
    return this.outbox
  }

  formalLeaseForFinalization() {
    return this.captureLease
  }

  shouldPreserveFormalOutbox() {
    return this.incompleteMarker.confirmed
  }

  isStopped() {
    return this.stopped
  }

  async stop() {
    if (this.stopped) return
    if (this.stopInProgress) return this.stopInProgress
    this.stopRequested = true
    this.cancelStartup()
    if (this.pendingSocket && this.pendingSocket.readyState < WebSocket.CLOSING) {
      this.pendingSocket.close(1000, 'capture stopped')
      this.pendingSocket = null
    }
    this.stopInProgress = (async () => {
      if (!this.microphoneStopped) {
        this.stopAudioGraph()
        this.microphoneStopped = true
        if (this.context && this.context.state !== 'closed') await this.context.close().catch(() => undefined)
        this.context = null
      }
      await this.frameWrites
      if (this.outbox || (this.failed && !this.incompleteMarker.confirmed)) {
        const drained = await waitForBrowserFormalOutboxDrain(
          {
            list: async () => {
              if (!this.outbox) {
                return [{ sequence: Number.MAX_SAFE_INTEGER, startSample: 0n, pcm: new Uint8Array([0, 0]) }]
              }
              let pending: BrowserFormalAudioFrame[]
              try {
                pending = await this.outbox!.list()
              } catch (error) {
                const detail = error instanceof Error ? error.message : String(error)
                this.failIncomplete(`浏览器录音缓存无法读取：${detail}`, true)
                return [{ sequence: Number.MAX_SAFE_INTEGER, startSample: 0n, pcm: new Uint8Array([0, 0]) }]
              }
              if (this.failed && !this.incompleteMarker.confirmed && pending.length === 0) {
                return [{ sequence: Number.MAX_SAFE_INTEGER, startSample: 0n, pcm: new Uint8Array([0, 0]) }]
              }
              return pending
            },
          },
          () => this.pumpFormalOutbox(),
          10_000,
          () => this.incompleteMarker.confirmed,
        )
        if (!drained) {
          const message = '仍有未获服务器确认的音频帧；录音缓存已保留，请恢复连接后再次停止录音'
          if (!this.drainFailureReported) {
            this.drainFailureReported = true
            this.onIncomplete?.(message)
          }
          throw new Error(message)
        }
      }
      this.stopped = true
      if (this.reconnectTimer !== undefined) window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = undefined
      if (this.socket && this.socket.readyState < WebSocket.CLOSING) {
        // Declare a clean stop before closing: the backend cannot tell an ordinary
        // stop from a dropped connection once the socket is gone, and would persist
        // the capture as INCOMPLETE, blocking record finalization. Frames and the
        // control message are ordered on the same connection, so the server sees
        // this before the disconnect. Skipped when the outbox could not be drained.
        if (this.kind === 'FORMAL' && !this.failed) {
          try {
            this.socket.send(JSON.stringify({ type: 'capture_finalize' }))
          } catch {
            // The server still completes the capture through the stop request.
          }
        }
        this.socket.close(1000, 'capture stopped')
      }
      this.stream = null
      this.context = null
      this.source = null
      this.analyser = null
      this.processor = null
      this.mute = null
      this.socket = null
    })()
    try {
      await this.stopInProgress
    } finally {
      this.stopInProgress = null
    }
  }
}

interface ActiveBrowserCapture {
  kind: CaptureKind
  url: string
  captureKey?: string
  streamer: BrowserPcmStreamer | null
  onAudioLevel: ((sample: BrowserAudioLevelSample) => void) | null
  cancelRequested: boolean
  startPromise: Promise<void>
}

class BrowserCaptureStartupCancelledError extends Error {
  constructor() {
    super('浏览器麦克风采集已取消')
    this.name = 'BrowserCaptureStartupCancelledError'
  }
}

let activeCapture: ActiveBrowserCapture | null = null
let refusedFormalCaptureLeaseKey: string | null = null
let pendingFormalOutboxFinalization: {
  captureKey: string
  outbox: BoundedBrowserAsrOutbox | null
  preserveUnacknowledged: boolean
  lease: BrowserFormalCaptureLease | null
} | null = null

type UnexpectedCloseListener = () => void
type IncompleteCaptureListener = (message: string) => void
type SupersededListener = (reason: string) => void
let formalUnexpectedCloseListener: UnexpectedCloseListener | null = null
let formalIncompleteCaptureListener: IncompleteCaptureListener | null = null
let formalSupersededListener: SupersededListener | null = null

/**
 * Fired when the formal browser ASR audio socket closes without the caller
 * stopping it. The interrogation store uses this to auto-restart capture.
 */
export function setBrowserAsrUnexpectedCloseListener(listener: UnexpectedCloseListener | null) {
  formalUnexpectedCloseListener = listener
}

export function setBrowserAsrIncompleteCaptureListener(listener: IncompleteCaptureListener | null) {
  formalIncompleteCaptureListener = listener
}

/**
 * Fired when the server refuses this socket because another connection already
 * streams the same capture. The page must stop quietly: reporting
 * capture_incomplete here would mark the *other* window's healthy recording as
 * broken, and auto-restarting would fight over the same capture forever.
 */
export function setBrowserAsrSupersededListener(listener: SupersededListener | null) {
  formalSupersededListener = listener
}

async function startCapture(
  kind: CaptureKind,
  url: string,
  captureKey?: string,
  onAudioLevel?: (sample: BrowserAudioLevelSample) => void,
) {
  const current = activeCapture
  const sameCapture = current?.kind === kind && (
    kind === 'FORMAL'
      ? captureKey !== undefined && current.captureKey === captureKey && current.url === url
      : current.url === url
  )
  if (current && sameCapture) {
    current.onAudioLevel = onAudioLevel ?? null
    if (current.streamer) current.streamer.onAudioLevel = current.onAudioLevel
    return current.startPromise
  }
  if (current) await stopBrowserAudioCapture()
  const finalization = kind === 'FORMAL'
    ? takeMatchingBrowserFormalFinalization(pendingFormalOutboxFinalization, captureKey)
    : { resumed: null, remaining: pendingFormalOutboxFinalization }
  const resumedFinalization = finalization.resumed
  pendingFormalOutboxFinalization = finalization.remaining
  const entry: ActiveBrowserCapture = {
    kind,
    url,
    captureKey,
    streamer: null,
    onAudioLevel: onAudioLevel ?? null,
    cancelRequested: false,
    startPromise: Promise.resolve(),
  }
  activeCapture = entry
  entry.startPromise = (async () => {
    let captureLease = resumedFinalization?.lease ?? undefined
    let streamer: BrowserPcmStreamer | null = null
    try {
      if (kind === 'FORMAL' && !captureLease) {
        captureLease = await acquireBrowserFormalCaptureLease(captureKey || '')
      }
      if (kind === 'FORMAL' && captureLease) {
        // A successfully acquired lease for a different capture supersedes any
        // stale conflict left by an older capture in this tab.
        refusedFormalCaptureLeaseKey = null
      }
      if (entry.cancelRequested) {
        if (resumedFinalization) pendingFormalOutboxFinalization = resumedFinalization
        else captureLease?.release()
        throw new BrowserCaptureStartupCancelledError()
      }
      streamer = new BrowserPcmStreamer()
      streamer.onAudioLevel = entry.onAudioLevel
      entry.streamer = streamer
      if (kind === 'FORMAL') {
        streamer.onUnexpectedClose = () => {
          if (activeCapture?.streamer === streamer) formalUnexpectedCloseListener?.()
        }
        streamer.onIncomplete = (message) => {
          if (activeCapture?.streamer === streamer) formalIncompleteCaptureListener?.(message)
        }
        streamer.onSuperseded = (reason) => {
          if (activeCapture?.streamer === streamer) formalSupersededListener?.(reason)
        }
      }
      await streamer.start(url, kind, captureKey, captureLease)
    } catch (error) {
      if (error instanceof BrowserFormalCaptureLeaseError && error.reason === 'CONFLICT') {
        refusedFormalCaptureLeaseKey = error.captureKey
      }
      if (resumedFinalization && !streamer) {
        pendingFormalOutboxFinalization = resumedFinalization
      } else if (streamer?.isStopped() && kind === 'FORMAL') {
        const outbox = streamer.formalOutboxForFinalization()
        pendingFormalOutboxFinalization = {
          captureKey: captureKey || '',
          outbox,
          preserveUnacknowledged: streamer.shouldPreserveFormalOutbox()
            || Boolean(resumedFinalization?.preserveUnacknowledged),
          lease: streamer.formalLeaseForFinalization(),
        }
      } else if (!streamer && !resumedFinalization) {
        captureLease?.release()
      }
      if (
        activeCapture === entry
        && !(kind === 'FORMAL' && streamer !== null && !streamer.isStopped())
      ) {
        activeCapture = null
      }
      throw error
    }
  })()
  return entry.startPromise
}

export async function startBrowserAsrCapture(
  caseId: string,
  captureId: string,
  origin = runtimeConfig.apiBaseUrl,
  onAudioLevel?: (sample: BrowserAudioLevelSample) => void,
) {
  return startCapture(
    'FORMAL',
    buildBrowserAsrCaptureWebSocketUrl(caseId, captureId, origin),
    `${caseId}:${captureId}`,
    onAudioLevel,
  )
}

export async function startBrowserQuestionPreparationCapture(
  caseId: string,
  captureId = 'question-preparation',
  origin = runtimeConfig.apiBaseUrl,
) {
  return startCapture('QUESTION_PREP', buildBrowserQuestionPreparationWebSocketUrl(caseId, captureId, origin))
}

export async function stopBrowserAudioCapture(kind?: CaptureKind) {
  const current = activeCapture
  if (
    refusedFormalCaptureLeaseKey
    && (kind === undefined || kind === 'FORMAL')
    && (!current || current.kind !== 'FORMAL')
  ) {
    throw new BrowserFormalCaptureLeaseError(refusedFormalCaptureLeaseKey, 'CONFLICT')
  }
  if (!current || (kind && current.kind !== kind)) return
  if (!current.streamer) {
    current.cancelRequested = true
    try {
      await current.startPromise
    } catch (error) {
      if (!(error instanceof BrowserCaptureStartupCancelledError) && !current.cancelRequested) throw error
      if (error instanceof BrowserFormalCaptureLeaseError && error.reason === 'CONFLICT') throw error
    }
    if (activeCapture === current) activeCapture = null
    return
  }
  let stopError: unknown
  try {
    await current.streamer.stop()
  } catch (error) {
    stopError = error
  }
  await current.startPromise.catch(() => undefined)
  if (current.streamer.isStopped()) {
    if (activeCapture === current) activeCapture = null
    if (current.kind === 'FORMAL') {
      const outbox = current.streamer.formalOutboxForFinalization()
      pendingFormalOutboxFinalization = outbox
        ? {
          outbox,
          captureKey: current.captureKey || '',
          preserveUnacknowledged: current.streamer.shouldPreserveFormalOutbox(),
          lease: current.streamer.formalLeaseForFinalization(),
        }
        : {
          outbox: null,
          captureKey: current.captureKey || '',
          preserveUnacknowledged: current.streamer.shouldPreserveFormalOutbox(),
          lease: current.streamer.formalLeaseForFinalization(),
        }
    }
  }
  if (stopError) throw stopError
}

export function clearBrowserAsrCaptureLeaseRefusal(caseId: string, captureId?: string | null) {
  if (!captureId) return
  if (refusedFormalCaptureLeaseKey === `${caseId}:${captureId}`) refusedFormalCaptureLeaseKey = null
}

export async function confirmBrowserAsrCaptureFinalized() {
  const pending = pendingFormalOutboxFinalization
  if (!pending) return
  if (pending.outbox) {
    await confirmBrowserFormalOutboxFinalization(pending.outbox, pending.preserveUnacknowledged)
  }
  pending.lease?.release()
  pendingFormalOutboxFinalization = null
}

export const stopBrowserAsrCapture = () => stopBrowserAudioCapture('FORMAL')
export const stopBrowserQuestionPreparationCapture = () => stopBrowserAudioCapture('QUESTION_PREP')
