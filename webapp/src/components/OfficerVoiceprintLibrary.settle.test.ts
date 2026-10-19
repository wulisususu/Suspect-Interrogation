import { readFileSync } from 'node:fs'
import { transformSync } from 'esbuild'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BrowserVoiceprintCapture } from '../audio/browserVoiceprintCapture'

/**
 * Integration test for the sample-enrollment settle race.
 *
 * `OfficerVoiceprintLibrary.vue` registers the transport callbacks that write
 * `error.value` directly. The backend closes the browser audio channel while the
 * HTTP stop/enroll request is still running, so a successful sample used to be
 * reported to the operator as a failure. This suite drives the real component
 * (compiled SFC, custom renderer, mocked API modules) to prove the notice stays
 * clean and that a genuine in-recording failure is still reported.
 */

type TestNode = {
  type: string
  text: string
  props: Record<string, unknown>
  children: TestNode[]
  parent: TestNode | null
}

function node(type: string, text = ''): TestNode {
  return { type, text, props: {}, children: [], parent: null }
}

function compileClientComponent(fileName: string, dependencies: Record<string, unknown>) {
  const source = readFileSync(new URL(fileName, import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: fileName })
  const script = compileScript(descriptor, { id: fileName })
  const template = compileTemplate({
    // This renderer has no document.body. Keep the real modal subtree inline;
    // actual Teleport placement and focus are verified in the browser.
    source: (descriptor.template?.content || '').replace('<Teleport to="body">', '<div>').replace('</Teleport>', '</div>'),
    filename: fileName,
    id: fileName,
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings, hoistStatic: false },
  })
  if (template.errors.length) throw new Error(String(template.errors[0]))
  const scriptWithoutImports = script.content
    // Multi-line import statements (including `import type { ... }`) go first:
    // every symbol they bind is injected as a dependency instead.
    .replace(/^import(?: type)? [\s\S]*?from\s+['"][^'"]+['"];?\r?\n/gm, '')
    .replace(/^export (?=(?:function|const|let|class) )/gm, '')
    .replace(/^export default /m, 'return ')
    .replace(/Object\.defineProperty\(__returned__, '__isScriptSetup', \{ enumerable: false, value: true \}\)\r?\n/, '')
  const factorySource = `return function createComponent(Vue, dependencies) {
    const { defineComponent: _defineComponent, computed, nextTick, onMounted, onUnmounted, ref, unref } = Vue
    const {
      audioInputMode,
      disableOfficerVoiceSample,
      fetchBrowserAwareVoiceprintStatus,
      fetchOfficerVoiceProfile,
      fetchOfficerVoiceProfiles,
      revokeOfficerVoiceProfile,
      selectVoiceprintSource,
      startBrowserAwareOfficerEnrollment,
      stopBrowserAwareOfficerEnrollment,
      vModelText,
    } = dependencies
    ${scriptWithoutImports}
  }`
  const createComponent = new Function(transformSync(factorySource, { loader: 'ts', target: 'es2022' }).code)()
  const component = createComponent(Vue, dependencies) as { render?: unknown }
  // The custom renderer has no DOM elements, so the compiled render function
  // must not receive the DOM `vModelText` directive (it would attach listeners
  // to the test's plain node objects). setInput() drives the emitted update
  // handler instead.
  component.render = new Function('Vue', template.code)({ ...Vue, vModelText: {} })
  return component
}

// Mutable holders: the compiled component captures these at build time, so the
// test must mutate the holder's contents, never the object identity.
const runtime = {
  capture: null as CaptureDouble | null,
  stopEnrollment: async (): Promise<Record<string, unknown>> => ({ officerId: 'P-001', officerName: '民警甲' }),
  status: { capturedDurationMs: 0, usableSpeechMs: 0, requiredUsableSpeechMs: 20_000, complete: false },
}

const api = {
  disableOfficerVoiceSample: async () => undefined,
  fetchBrowserAwareVoiceprintStatus: async () => runtime.status,
  fetchOfficerVoiceProfile: async (officerId: string) => ({
    profileId: 'profile-1', officerId, officerName: '民警甲', active: true,
    sampleCount: 2, aggregateVersion: 2, usableDurationMs: 43_000, embeddingDim: 3,
    modelId: 'eres2net-large', modelVersion: 'v1', quality: 'AGGREGATED',
  }),
  fetchOfficerVoiceProfiles: async () => [{
    profileId: 'profile-1', officerId: 'P-001', officerName: '民警甲', active: true,
    sampleCount: 2, aggregateVersion: 2, usableDurationMs: 43_000, embeddingDim: 3,
    modelId: 'eres2net-large', modelVersion: 'v1', quality: 'AGGREGATED',
  }],
  revokeOfficerVoiceProfile: async () => undefined,
  selectVoiceprintSource: async () => ({
    source: 'BROWSER' as const,
    browserCapture: runtime.capture as unknown as BrowserVoiceprintCapture,
    reason: '',
  }),
  startBrowserAwareOfficerEnrollment: async () => ({ captureId: 'capture-officer' }),
  stopBrowserAwareOfficerEnrollment: () => runtime.stopEnrollment(),
}

const OfficerVoiceprintLibrary = compileClientComponent('./OfficerVoiceprintLibrary.vue', {
  audioInputMode: 'BROWSER',
  // v-model on a custom renderer: the DOM directive attaches listeners to a real
  // element, so the test injects a no-op and drives the emitted update handler.
  vModelText: {} as { created?: () => void },
  ...api,
})

const renderer = Vue.createRenderer<TestNode, TestNode>({
  patchProp(element, key, _previous, next) { element.props[key] = next },
  insert(child, parent, anchor) {
    child.parent = parent
    if (anchor) parent.children.splice(parent.children.indexOf(anchor), 0, child)
    else parent.children.push(child)
  },
  remove(child) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
  },
  createElement(type) { return node(type) },
  createText(text) { return node('#text', text) },
  createComment(text) { return node('#comment', text) },
  setText(target, text) { target.text = text },
  setElementText(target, text) { target.children = []; target.text = text },
  parentNode(target) { return target.parent },
  nextSibling(target) {
    const siblings = target.parent?.children ?? []
    return siblings[siblings.indexOf(target) + 1] ?? null
  },
})

type Harness = {
  root: TestNode
  capture: CaptureDouble
  start: () => Promise<void>
  stop: () => Promise<void>
  acceptStop: () => void
  stopPending: () => boolean
}

class CaptureDouble {
  readonly actions: string[] = []
  callbacks: { onError?: (message: string) => void; onTrackEnded?: () => void } = {}
  private state: 'STOPPED' | 'STREAMING' | 'FINALIZING' = 'STOPPED'

  async start(_captureId: string, callbacks: { onError?: (message: string) => void; onTrackEnded?: () => void } = {}) {
    this.actions.push('capture:start')
    this.callbacks = callbacks
    this.state = 'STREAMING'
  }

  pause() {
    this.actions.push('capture:pause')
    if (this.state === 'STREAMING') this.state = 'FINALIZING'
  }

  async stop() {
    this.actions.push('capture:stop')
    this.state = 'STOPPED'
  }

  /** The backend hangs up the browser audio channel during the HTTP stop. */
  emitTransportError(message = '浏览器麦克风音频通道已断开，请重新开始声纹录制') {
    this.callbacks.onError?.(message)
  }
}

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function allNodes(target: TestNode): TestNode[] {
  return [target, ...target.children.flatMap(allNodes)]
}

function findNode(target: TestNode, predicate: (item: TestNode) => boolean): TestNode {
  if (predicate(target)) return target
  for (const child of target.children) {
    try {
      return findNode(child, predicate)
    } catch {
      // Search the next sibling subtree.
    }
  }
  throw new Error('Matching node not found')
}

function textContent(target: TestNode): string {
  return `${target.text}${target.children.map(textContent).join('')}`
}

function alertText(root: TestNode): string {
  const alerts = allNodes(root).filter((item) => item.props.role === 'alert')
  if (!alerts.length) return ''
  return textContent(alerts[0]!).trim()
}

function click(root: TestNode, label: string) {
  const button = findNode(root, (item) => item.type === 'button' && textContent(item).includes(label))
  ;(button.props.onClick as () => void)()
}

function setInput(root: TestNode, placeholder: string, value: string) {
  const input = findNode(root, (item) => item.type === 'input' && item.props.placeholder === placeholder)
  const onUpdate = input.props['onUpdate:modelValue'] as ((next: string) => void) | undefined
  if (!onUpdate) throw new Error(`input ${placeholder} has no v-model handler`)
  onUpdate(value)
}

function setupHarness(): Harness {
  const capture = new CaptureDouble()
  runtime.capture = capture
  const pendingStopSettlers: Array<() => void> = []
  runtime.stopEnrollment = () => new Promise((resolve) => {
    pendingStopSettlers.push(() => resolve({ officerId: 'P-001', officerName: '民警甲' }))
  })

  const root = node('root')
  const app = renderer.createApp(OfficerVoiceprintLibrary, {})
  app.provide(Vue.ssrContextKey, { modules: new Set<string>() })
  app.mount(root)

  const start = async () => {
    click(root, '新增声纹登记')
    await flush()
    setInput(root, '例如 P-001', 'P-001')
    setInput(root, '请输入姓名', '民警甲')
    click(root, '开始添加新样本')
    await flush()
    await flush()
  }
  const stop = async () => {
    click(root, '提前停止并保存样本')
    await flush()
  }

  return {
    root,
    capture,
    start,
    stop,
    acceptStop: () => {
      const settlers = pendingStopSettlers.splice(0, pendingStopSettlers.length)
      for (const settle of settlers) settle()
    },
    stopPending: () => pendingStopSettlers.length > 0,
  }
}

describe('OfficerVoiceprintLibrary settle race', () => {
  beforeEach(() => {
    vi.useRealTimers()
    runtime.status = { capturedDurationMs: 0, usableSpeechMs: 0, requiredUsableSpeechMs: 20_000, complete: false }
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('stops the transport and reports success when the channel closes during the HTTP stop', async () => {
    const harness = setupHarness()
    await harness.start()
    expect(harness.capture.actions).toContain('capture:start')

    const stopping = harness.stop()
    await flush()
    // Production race: the backend already stored the sample and hangs up the
    // browser audio channel before the HTTP stop response arrives.
    expect(harness.stopPending()).toBe(true)
    expect(harness.capture.actions).toContain('capture:pause')
    harness.capture.emitTransportError()

    harness.acceptStop()
    await stopping

    expect(harness.capture.actions).toContain('capture:stop')
    // The success state is the final one: the settle race must not leave an
    // error notice behind a stored sample.
    expect(alertText(harness.root)).toBe('')
    expect(harness.capture.actions.filter((action) => action === 'capture:stop')).toHaveLength(1)
  })

  it('still reports a transport failure that happens while sampling', async () => {
    const harness = setupHarness()
    await harness.start()

    harness.capture.emitTransportError('麦克风已拔出')
    await flush()

    expect(alertText(harness.root)).toBe('麦克风已拔出')
  })
})
