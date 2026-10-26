import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BrowserVoiceprintCapture } from '../audio/browserVoiceprintCapture'
import type { VoiceprintEnrollmentState } from '../types/interrogation'

/**
 * The vitest environment is node: the store and the runtime config read
 * `window.location` at module import time, so these globals must be installed
 * before the modules under test are imported.
 */
type BrowserGlobalScope = {
  window?: unknown
  location?: unknown
  isSecureContext?: unknown
  WebSocket?: unknown
}

function installBrowserGlobals() {
  const scope = globalThis as unknown as BrowserGlobalScope
  const original = {
    window: scope.window,
    location: scope.location,
    isSecureContext: scope.isSecureContext,
    WebSocket: scope.WebSocket,
  }
  const location = {
    origin: 'https://192.168.0.9:18080',
    search: '?caseId=CASE-RACE',
    hostname: '192.168.0.9',
    href: 'https://192.168.0.9:18080/?caseId=CASE-RACE',
  }
  scope.location = location
  scope.isSecureContext = true
  // Present only so nothing accidentally reaches a real constructor; the
  // capture object used by this suite is a double.
  scope.WebSocket = class {
    close() { /* not used */ }
  }
  scope.window = {
    location,
    isSecureContext: true,
    AudioContext: class { /* not used */ },
  }
  return () => {
    scope.window = original.window
    scope.location = original.location
    scope.isSecureContext = original.isSecureContext
    scope.WebSocket = original.WebSocket
  }
}

const restoreBrowserGlobals = installBrowserGlobals()

const apiMock = vi.hoisted(() => ({
  startBrowserAwareSuspectEnrollment: vi.fn(),
  stopBrowserAwareSuspectEnrollment: vi.fn(),
  startBrowserAwareOfficerEnrollment: vi.fn(),
  stopBrowserAwareOfficerEnrollment: vi.fn(),
  cancelBrowserAwareVoiceprintEnrollment: vi.fn(),
  fetchBrowserAwareVoiceprintStatus: vi.fn(),
}))

const selectionMock = vi.hoisted(() => ({
  selectAutoVoiceprintSource: vi.fn(),
}))

vi.mock('../api/browserVoiceprint', () => apiMock)
vi.mock('../audio/voiceprintSourceSelection', () => selectionMock)

const FINALIZE_ACTION = 'capture:beginFinalize'
const HTTP_STOP_ACTION = 'http:stop'
const STOP_CAPTURE_ACTION = 'capture:stop'

/**
 * Records lifecycle call order. `lifecycleSemantics: 'legacy'` makes the double
 * behave like the unfixed capture, where every channel close is reported as an
 * error; that isolates the composable's own terminal-state guard.
 */
class ActionCapture {
  readonly inputSampleRate: number | null = null
  readonly actions: string[] = []
  readonly callbacks: { onError?: (message: string) => void; onTrackEnded?: () => void } = {}
  lifecycleSemantics: 'stateful' | 'legacy' = 'stateful'
  /** Number of onError callbacks the transport actually delivered. */
  errorDeliveries = 0
  private state: 'CONNECTING' | 'STREAMING' | 'FINALIZING' | 'STOPPED' = 'STOPPED'

  get lifecycle() {
    return this.state
  }

  async start(
    _captureId: string,
    callbacks: { onError?: (message: string) => void; onTrackEnded?: () => void } = {},
  ) {
    this.actions.push('capture:start')
    Object.assign(this.callbacks, callbacks)
    this.state = 'STREAMING'
  }

  /** Makes beginFinalize() throw, like a transport that cannot leave STREAMING. */
  beginFinalizeThrows = false

  beginFinalize() {
    this.actions.push(FINALIZE_ACTION)
    if (this.beginFinalizeThrows) throw new Error('浏览器麦克风无法进入收尾状态')
    if (this.state !== 'STOPPED') this.state = 'FINALIZING'
  }

  pause() {
    this.actions.push('capture:pause')
    if (this.lifecycleSemantics === 'legacy') return
    if (this.state === 'STREAMING') this.state = 'FINALIZING'
  }

  async stop() {
    this.actions.push(STOP_CAPTURE_ACTION)
    this.state = 'STOPPED'
  }

  /**
   * Backend-side close of the browser audio channel. With `stateful` semantics
   * the FINALIZING state suppresses it (the fixed capture); with `legacy`
   * semantics every close is reported, which is what the buggy capture did.
   */
  emitClose() {
    if (this.lifecycleSemantics === 'legacy' || this.state === 'STREAMING') {
      this.errorDeliveries += 1
      this.callbacks.onError?.('浏览器麦克风音频通道已断开，请重新开始声纹录制')
    }
  }

  emitTrackEnded() {
    this.callbacks.onTrackEnded?.()
  }
}

type Harness = {
  /** The capture double handed to the most recent start attempt. */
  readonly capture: ActionCapture
  /** Every capture double created so far, oldest first. */
  captures: () => ActionCapture[]
  /** Hand this double to the next start attempt. */
  nextCapture: (capture: ActionCapture) => void
  actions: string[]
  state: () => VoiceprintEnrollmentState
  /** True while the store reports a voiceprint operation in flight. */
  busy: () => boolean
  /**
   * Make the post-stop state refresh fail, as a timed-out readiness/officer
   * round trip does on a slow board.
   */
  failRefresh: (error?: Error) => void
  feedbackCalls: () => Array<{ message: string; isError: boolean }>
  startSuspect: () => Promise<void>
  stopSuspect: () => Promise<void>
  startOfficer: () => Promise<void>
  stopOfficer: () => Promise<void>
  /** Resolve the pending HTTP stop/enroll request. */
  acceptEnrollment: () => void
  /** Reject the pending HTTP stop/enroll request. */
  rejectEnrollment: (error: Error) => void
  /** True while at least one HTTP stop/enroll request is still in flight. */
  httpStopPending: () => boolean
  /** Resolve every cancel request that is still in flight. */
  settle: () => Promise<void>
  /** Hold cancel responses open so the test controls their timing. */
  deferCancels: () => void
  /** True while at least one cancel request is still in flight. */
  cancelPending: () => boolean
  dispose: () => Promise<void>
}

async function createHarness(): Promise<Harness> {
  vi.resetModules()

  let pendingCancel: (() => void) | undefined
  let deferCancelResponses = false

  const captures: ActionCapture[] = []
  let activeCapture = new ActionCapture()
  captures.push(activeCapture)

  selectionMock.selectAutoVoiceprintSource.mockImplementation(async () => ({
    source: 'BROWSER',
    browserCapture: activeCapture as unknown as BrowserVoiceprintCapture,
    reason: '测试音源：本机浏览器麦克风',
  }))
  apiMock.startBrowserAwareSuspectEnrollment.mockResolvedValue({ captureId: 'capture-race-suspect', ready: true })
  apiMock.startBrowserAwareOfficerEnrollment.mockResolvedValue({ captureId: 'capture-race-officer', ready: true })
  apiMock.fetchBrowserAwareVoiceprintStatus.mockResolvedValue({
    active: false,
    captureId: 'capture-race-suspect',
    capturedDurationMs: 0,
    complete: false,
  })
  apiMock.cancelBrowserAwareVoiceprintEnrollment.mockImplementation(async () => {
    if (!deferCancelResponses) return
    await new Promise<void>((resolve) => { pendingCancel = resolve })
  })
  const enrollmentResults: Array<Record<string, unknown>> = [
    { usableDurationMs: 20_030, simulated: false },
    { usableDurationMs: 20_030, simulated: false, officerName: '民警甲' },
  ]
  const pendingStopSettlers: Array<{ resolve: (value: Record<string, unknown>) => void; reject: (reason: Error) => void }> = []
  const stopEnrollment = () => {
    activeCapture.actions.push(HTTP_STOP_ACTION)
    return new Promise<Record<string, unknown>>((resolve, reject) => {
      pendingStopSettlers.push({ resolve, reject })
    })
  }
  apiMock.stopBrowserAwareSuspectEnrollment.mockImplementation(stopEnrollment)
  apiMock.stopBrowserAwareOfficerEnrollment.mockImplementation(stopEnrollment)

  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const { useInterrogationStore } = await import('../stores/interrogation')
  const store = useInterrogationStore()
  // The spy is kept so a test can make the refresh reject. A resolving default
  // keeps every other case on the happy path.
  const refreshVoiceprintState = vi.spyOn(store, 'refreshVoiceprintState').mockResolvedValue(undefined)
  const feedbackCalls: Array<{ message: string; isError: boolean }> = []
  vi.spyOn(store, 'feedback').mockImplementation((message: string, isError = false) => {
    feedbackCalls.push({ message, isError })
  })

  const { useAutoVoiceprintEnrollment } = await import('./useAutoVoiceprintEnrollment')
  const enrollment = useAutoVoiceprintEnrollment()

  return {
    get capture() {
      return activeCapture
    },
    captures: () => captures,
    nextCapture: (capture: ActionCapture) => {
      activeCapture = capture
      captures.push(capture)
    },
    actions: [],
    state: () => store.voiceprintEnrollmentState,
    busy: () => store.voiceprintBusy,
    failRefresh: (error: Error = new Error('声纹状态刷新失败')) => {
      refreshVoiceprintState.mockRejectedValue(error)
    },
    feedbackCalls: () => feedbackCalls,
    startSuspect: () => enrollment.startSuspect(),
    stopSuspect: () => enrollment.stopSuspect(),
    startOfficer: () => enrollment.startOfficer('OFFICER-1', '民警甲'),
    stopOfficer: () => enrollment.stopOfficer('OFFICER-1'),
    acceptEnrollment: () => {
      const settlers = pendingStopSettlers.splice(0, pendingStopSettlers.length)
      for (const settler of settlers) settler.resolve(enrollmentResults.shift() ?? { usableDurationMs: 20_030, simulated: false })
    },
    rejectEnrollment: (error: Error) => {
      const settlers = pendingStopSettlers.splice(0, pendingStopSettlers.length)
      for (const settler of settlers) settler.reject(error)
    },
    httpStopPending: () => pendingStopSettlers.length > 0,
    settle: async () => {
      pendingCancel?.()
      pendingCancel = undefined
      await flush()
      await flush()
    },
    deferCancels: () => { deferCancelResponses = true },
    cancelPending: () => pendingCancel !== undefined,
    dispose: () => enrollment.dispose(),
  }
}

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

describe('useAutoVoiceprintEnrollment lifecycle race', () => {
  beforeAll(() => {
    vi.useRealTimers()
  })

  afterAll(() => {
    restoreBrowserGlobals()
  })

  beforeEach(() => {
    for (const fn of Object.values(apiMock)) fn.mockReset()
    selectionMock.selectAutoVoiceprintSource.mockReset()
  })

  it('keeps COMPLETE when the audio channel closes during the HTTP stop, instead of rewriting it into ERROR', { timeout: 20000 }, async () => {
    const harness = await createHarness()
    // Legacy transport semantics: every close is reported as an error, exactly
    // like the pre-fix capture. Only the composable's own state guards can keep
    // COMPLETE intact here.
    harness.capture.lifecycleSemantics = 'legacy'
    await harness.startSuspect()
    expect(harness.state().phase).toBe('RECORDING')

    const stopping = harness.stopSuspect()
    await flush()

    // Production race: the backend already finished enrollment (quality=GOOD,
    // usable=20030 ms) and closed the browser audio channel while the HTTP stop
    // response was still in flight.
    expect(harness.httpStopPending()).toBe(true)
    harness.capture.emitClose()
    expect(harness.capture.errorDeliveries).toBe(1)
    expect(harness.state().phase).toBe('PROCESSING')

    harness.acceptEnrollment()
    await stopping

    expect(harness.state().phase).toBe('COMPLETE')
    expect(harness.state().usableDurationMs).toBe(20_030)
    expect(harness.state().message).toContain('已注册')
    // The failure must never be surfaced to the operator either: no error toast
    // while the enrollment was still being registered, and a success toast last.
    expect(harness.feedbackCalls().filter((call) => call.isError)).toEqual([])
    expect(harness.feedbackCalls().at(-1)).toEqual({ message: '嫌疑人声纹已注册', isError: false })

    // A repeated transport callback after COMPLETE is terminal: it must not
    // resurrect ERROR or a failure toast.
    harness.capture.emitClose()
    await flush()
    expect(harness.state().phase).toBe('COMPLETE')
    expect(harness.feedbackCalls().filter((call) => call.isError)).toEqual([])
  })

  it('finalizes the transport before the HTTP stop and only closes the capture afterwards', { timeout: 20000 }, async () => {
    const harness = await createHarness()
    await harness.startSuspect()

    const stopping = harness.stopSuspect()
    await flush()

    expect(harness.capture.actions).toContain(FINALIZE_ACTION)
    expect(harness.capture.actions).not.toContain(STOP_CAPTURE_ACTION)

    harness.acceptEnrollment()
    await stopping

    const finalizeAt = harness.capture.actions.indexOf(FINALIZE_ACTION)
    const httpAt = harness.capture.actions.indexOf(HTTP_STOP_ACTION)
    const stopAt = harness.capture.actions.indexOf(STOP_CAPTURE_ACTION)
    expect(finalizeAt).toBeGreaterThanOrEqual(0)
    expect(httpAt).toBeGreaterThan(finalizeAt)
    expect(stopAt).toBeGreaterThan(httpAt)
    expect(harness.state().phase).toBe('COMPLETE')
  })

  it('keeps COMPLETE for an officer enrollment when the channel closes during the HTTP stop', async () => {
    const harness = await createHarness()
    harness.capture.lifecycleSemantics = 'legacy'
    await harness.startOfficer()

    const stopping = harness.stopOfficer()
    await flush()

    expect(harness.httpStopPending()).toBe(true)
    harness.capture.emitClose()
    harness.acceptEnrollment()
    await stopping

    expect(harness.state().phase).toBe('COMPLETE')
    expect(harness.state().usableDurationMs).toBe(20_030)
    expect(harness.state().message).toContain('已保存')
    expect(harness.feedbackCalls().filter((call) => call.isError)).toEqual([])
    expect(harness.feedbackCalls().at(-1)?.message).toContain('已保存')
  })

  it('still reports a real transport failure that happens while recording', async () => {
    const harness = await createHarness()
    harness.capture.lifecycleSemantics = 'legacy'
    await harness.startSuspect()

    harness.capture.emitClose()
    await harness.settle()

    expect(harness.state().phase).toBe('ERROR')
    expect(harness.state().message).toContain('音频通道已断开')
    expect(apiMock.cancelBrowserAwareVoiceprintEnrollment).toHaveBeenCalledWith('capture-race-suspect')
    expect(harness.capture.actions).toContain(STOP_CAPTURE_ACTION)
    expect(harness.feedbackCalls().at(-1)).toEqual({
      message: '浏览器麦克风音频通道已断开，请重新开始声纹录制',
      isError: true,
    })
  })

  it('ignores a late transport callback after a completed enrollment', async () => {
    const harness = await createHarness()
    await harness.startSuspect()

    const stopping = harness.stopSuspect()
    await flush()
    harness.acceptEnrollment()
    await stopping
    expect(harness.state().phase).toBe('COMPLETE')

    harness.capture.emitClose()
    harness.capture.emitTrackEnded()
    await flush()

    expect(harness.state().phase).toBe('COMPLETE')
    expect(harness.feedbackCalls().filter((call) => call.isError)).toEqual([])
  })

  it('never lets a previous attempt callback fail the next recording round', async () => {
    const harness = await createHarness()
    const firstRound = harness.capture
    firstRound.lifecycleSemantics = 'legacy'
    await harness.startSuspect()

    const stopping = harness.stopSuspect()
    await flush()
    harness.acceptEnrollment()
    await stopping
    // No pending cancel: this test is about stale callbacks, not about a
    // cancellation still being applied on the server (covered below).
    await harness.settle()
    expect(harness.state().phase).toBe('COMPLETE')

    // Second round: a brand new capture double, exactly like a fresh recording.
    const secondRound = new ActionCapture()
    secondRound.lifecycleSemantics = 'legacy'
    harness.nextCapture(secondRound)
    await harness.startSuspect()
    expect(harness.state().phase).toBe('RECORDING')
    expect(secondRound.actions).toContain('capture:start')

    // Replay every late callback the finished first round could still deliver.
    firstRound.emitClose()
    firstRound.emitTrackEnded()
    await harness.settle()

    expect(harness.state().phase).toBe('RECORDING')
    expect(harness.state().subjectId).toBe('CASE-RACE')
    expect(harness.feedbackCalls().filter((call) => call.isError)).toEqual([])
    expect(apiMock.cancelBrowserAwareVoiceprintEnrollment).not.toHaveBeenCalled()

    // The second round still finalizes normally.
    const secondStopping = harness.stopSuspect()
    await flush()
    harness.capture.emitClose()
    harness.acceptEnrollment()
    await secondStopping
    expect(harness.state().phase).toBe('COMPLETE')
  })

  it('drops a cancellation that is still in flight when a new round starts', async () => {
    const harness = await createHarness()
    harness.deferCancels()
    const firstRound = harness.capture
    // A close while streaming starts the real cancel path (and its ERROR write).
    harness.capture.lifecycleSemantics = 'legacy'
    await harness.startSuspect()
    firstRound.emitClose()
    await flush()
    expect(harness.cancelPending()).toBe(true)
    // A late delivery that belongs to the failed first round: emitted again
    // after the next round already started.
    const lateCallbacks = firstRound.callbacks

    // The failed attempt settles and its cancellation is applied on the server.
    await harness.settle()
    expect(harness.state().phase).toBe('ERROR')
    expect(harness.cancelPending()).toBe(false)

    // A new round starts, then the failed round delivers its callbacks late.
    const secondRound = new ActionCapture()
    secondRound.lifecycleSemantics = 'legacy'
    harness.nextCapture(secondRound)
    await harness.startSuspect()
    expect(harness.state().phase).toBe('RECORDING')

    lateCallbacks.onError?.('浏览器麦克风音频通道已断开，请重新开始声纹录制')
    lateCallbacks.onTrackEnded?.()
    await flush()

    expect(harness.state().phase).toBe('RECORDING')
    expect(harness.feedbackCalls().filter((call) => call.isError).length).toBe(1)

    // The running round still finalizes normally.
    const stopping = harness.stopSuspect()
    await flush()
    secondRound.emitClose()
    harness.acceptEnrollment()
    await stopping
    expect(harness.state().phase).toBe('COMPLETE')
  })

  it('refuses to start a new round while the previous cancellation is outstanding', async () => {
    const harness = await createHarness()
    harness.deferCancels()
    const firstRound = harness.capture
    harness.capture.lifecycleSemantics = 'legacy'
    await harness.startSuspect()
    firstRound.emitClose()
    await flush()
    expect(harness.cancelPending()).toBe(true)

    // While the cancel response is outstanding, a new recording must be refused
    // so the late cancel response cannot race a freshly started capture.
    const secondRound = new ActionCapture()
    secondRound.lifecycleSemantics = 'legacy'
    harness.nextCapture(secondRound)
    await harness.startSuspect()
    expect(secondRound.actions).toEqual([])

    await harness.settle()
    expect(harness.state().phase).toBe('ERROR')

    // And the next round works normally once the cancellation settled.
    await harness.startSuspect()
    expect(harness.state().phase).toBe('RECORDING')
    expect(secondRound.actions).toContain('capture:start')
  })

  it('releases the transport when the post-stop state refresh fails, and still reports the failure', async () => {
    const harness = await createHarness()
    await harness.startSuspect()
    const capture = harness.capture
    // The HTTP stop/enroll already succeeded on the backend; the refresh that
    // follows it is what fails (a readiness/officer round trip that times out on
    // a slow board). The audio channel has been closed by the backend by now, so
    // leaving the browser transport open keeps the microphone hot forever.
    harness.failRefresh(new Error('声纹就绪状态读取超时'))

    const stopping = harness.stopSuspect()
    await flush()
    harness.acceptEnrollment()
    await stopping

    expect(capture.actions).toContain(STOP_CAPTURE_ACTION)
    expect(capture.lifecycle).toBe('STOPPED')
    // The failure is still reported: a failed refresh must not be swallowed.
    expect(harness.state().phase).toBe('ERROR')
    expect(harness.state().subjectId).toBe('CASE-RACE')
    expect(harness.feedbackCalls().at(-1)?.isError).toBe(true)
    // ...and the block the failure left behind is released.
    expect(harness.busy()).toBe(false)

    // The leaked channel used to keep activeCaptureId pinned, so the operator
    // could never start the next round without reloading the page.
    const nextRound = new ActionCapture()
    harness.nextCapture(nextRound)
    await harness.startSuspect()
    expect(harness.state().phase).toBe('RECORDING')
    expect(nextRound.actions).toContain('capture:start')
  })

  it('releases the officer transport when the post-stop state refresh fails', async () => {
    const harness = await createHarness()
    await harness.startOfficer()
    const capture = harness.capture
    harness.failRefresh(new Error('民警声纹列表读取失败'))

    const stopping = harness.stopOfficer()
    await flush()
    harness.acceptEnrollment()
    await stopping

    expect(capture.actions).toContain(STOP_CAPTURE_ACTION)
    expect(capture.lifecycle).toBe('STOPPED')
    expect(harness.state().phase).toBe('ERROR')
    expect(harness.busy()).toBe(false)
  })

  it('releases the busy flag when the cancellation settles while a newer round is already running', async () => {
    const harness = await createHarness()
    harness.deferCancels()
    await harness.startSuspect()
    harness.capture.emitClose()
    await flush()
    expect(harness.cancelPending()).toBe(true)

    // The failed attempt's cancellation is still in flight when a new round
    // takes over: the stale cancel must not leave voiceprintBusy behind, or the
    // operator can never stop the round now recording.
    const nextRound = new ActionCapture()
    harness.nextCapture(nextRound)
    await harness.startSuspect()
    expect(harness.busy()).toBe(true)

    await harness.settle()

    // The stale cancellation keeps its own failure state and must not touch the
    // running round's, but it must hand voiceprintBusy back so the operator is
    // never locked out of the next attempt.
    expect(harness.busy()).toBe(false)
    expect(harness.state().phase).toBe('ERROR')

    const laterRound = new ActionCapture()
    harness.nextCapture(laterRound)
    await harness.startSuspect()
    expect(harness.state().phase).toBe('RECORDING')
    expect(laterRound.actions).toContain('capture:start')
  })

  it('resets the busy flag when beginFinalize throws, so the next round can start', async () => {
    const harness = await createHarness()
    await harness.startSuspect()
    // The transport refuses to leave STREAMING, so the finalize step itself
    // throws before any HTTP stop was attempted.
    harness.capture.beginFinalizeThrows = true

    const stopping = harness.stopSuspect()
    await flush()
    // Nothing to release: the operator must never be locked out of recording.
    expect(harness.busy()).toBe(false)
    expect(harness.httpStopPending()).toBe(false)

    await stopping

    expect(harness.busy()).toBe(false)
    expect(harness.state().phase).toBe('ERROR')

    // A permanent voiceprintBusy would keep every record button disabled.
    const nextRound = new ActionCapture()
    harness.nextCapture(nextRound)
    await harness.startSuspect()
    expect(nextRound.actions).toContain('capture:start')
    expect(harness.state().phase).toBe('RECORDING')
  })
})
