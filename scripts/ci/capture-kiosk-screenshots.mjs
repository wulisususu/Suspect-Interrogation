#!/usr/bin/env node
import { execFileSync, spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import process from 'node:process'

const baseUrl = process.env.KIOSK_URL || 'http://127.0.0.1:5173'
const caseId = process.env.KIOSK_CASE_ID || ''
const outputDir = process.env.KIOSK_SCREENSHOT_DIR || 'artifacts/kiosk-visual-qa'
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9222)

const visualFixture = {
  formalQuestion: '你什么时候到现场？',
  formalAnswer: '晚上八点左右。',
  rawOfficerMatched: '你什么时候到现场的？',
  rawOfficerUnmatched: '你把钥匙放到哪里去了？',
  rawSuspectMatched: '晚上八点左右。',
  rawSuspectUnmatched: '我放在门口鞋柜里了。',
  pendingTitle: '未匹配正式笔录问题',
}

if (!caseId) {
  console.error('KIOSK_CASE_ID is required')
  process.exit(2)
}

function which(command) {
  try {
    return execFileSync('which', [command], { encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function resolveChrome() {
  const explicit = process.env.CHROME_BIN
  if (explicit) return explicit
  for (const candidate of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']) {
    const resolved = which(candidate)
    if (resolved) return resolved
  }
  throw new Error('Chrome/Chromium was not found on the hosted runner')
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function waitFor(fn, description, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const value = await fn()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await sleep(250)
  }
  throw new Error(`Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ''}`)
}

class CdpClient {
  constructor(url) {
    this.url = url
    this.socket = null
    this.nextId = 1
    this.pending = new Map()
    this.events = []
  }

  async connect() {
    this.socket = new WebSocket(this.url)
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('CDP websocket connection timed out')), 10_000)
      this.socket.addEventListener('open', () => {
        clearTimeout(timer)
        resolve()
      }, { once: true })
      this.socket.addEventListener('error', (event) => {
        clearTimeout(timer)
        reject(new Error(`CDP websocket error: ${event.message || 'unknown error'}`))
      }, { once: true })
      this.socket.addEventListener('message', (event) => {
        const message = JSON.parse(String(event.data))
        if (!message.id) {
          if (['Runtime.exceptionThrown', 'Runtime.consoleAPICalled', 'Log.entryAdded'].includes(message.method)) {
            this.events.push(message)
            if (this.events.length > 50) this.events.shift()
            console.error(`browser-event=${JSON.stringify(message)}`)
          }
          return
        }
        const pending = this.pending.get(message.id)
        if (!pending) return
        this.pending.delete(message.id)
        if (message.error) pending.reject(new Error(message.error.message || 'CDP command failed'))
        else pending.resolve(message.result || {})
      })
    })
  }

  send(method, params = {}) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error('CDP websocket is not open'))
    }
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }

  close() {
    this.socket?.close()
  }
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Browser evaluation failed')
  return result.result?.value
}

async function inspectVisualFixture(client) {
  return evaluate(client, `(() => {
    const fixture = ${JSON.stringify(visualFixture)}
    const questionValues = Array.from(document.querySelectorAll('.body-question .editable-question textarea'))
      .map((item) => item.value || '')
    const answerValues = Array.from(document.querySelectorAll('.body-question .record-answer textarea'))
      .map((item) => item.value || '')
    const rawTurns = Array.from(document.querySelectorAll('.dialogue-bubble'))
      .map((item) => item.textContent || '')
    const pendingTexts = Array.from(document.querySelectorAll('.pending-resolution-card'))
      .map((item) => item.textContent || '')
    const questionVisible = questionValues.some((value) => value.includes(fixture.formalQuestion))
    const answerVisible = answerValues.some((value) => value.includes(fixture.formalAnswer))
    const rawText = rawTurns.join('\\n')
    const rawVisible = [
      fixture.rawOfficerMatched,
      fixture.rawOfficerUnmatched,
      fixture.rawSuspectMatched,
      fixture.rawSuspectUnmatched,
    ].every((text) => rawText.includes(text))
    const pendingCard = pendingTexts.some((text) => text.includes(fixture.pendingTitle)
      && text.includes('加入本案笔录')
      && text.includes('忽略'))
    return {
      complete: questionVisible && answerVisible && rawVisible && pendingCard,
      questionVisible,
      answerVisible,
      rawVisible,
      pendingCard,
      questionValues,
      answerValues,
      rawTurns,
      pendingTexts,
      bodyQuestionCount: questionValues.length,
      dialogueCount: rawTurns.length,
      pendingCount: pendingTexts.length,
      url: location.href,
    }
  })()`)
}

async function waitForSelector(client, selector, timeoutMs = 30_000) {
  try {
    return await waitFor(
      async () => evaluate(client, `Boolean(document.querySelector(${JSON.stringify(selector)}))`),
      selector,
      timeoutMs,
    )
  } catch (error) {
    const diagnostic = await evaluate(client, `(() => ({
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      appHtml: (document.querySelector('#app')?.innerHTML || '').slice(0, 4000),
      bodyText: (document.body?.innerText || '').slice(0, 4000),
      maintenance: Boolean(document.querySelector('.maintenance-shell')),
      caseRoot: Boolean(document.querySelector('.case-root-shell')),
      caseList: Boolean(document.querySelector('.case-list-page')),
      resources: performance.getEntriesByType('resource').map((entry) => entry.name).slice(-40),
    }))()`)
    console.error(`selector-timeout-diagnostic=${JSON.stringify(diagnostic)}`)
    console.error(`browser-events-snapshot=${JSON.stringify(client.events.slice(-20))}`)
    throw error
  }
}

async function clickButtonContaining(client, text) {
  const expression = `(() => {
    const target = Array.from(document.querySelectorAll('button')).find((button) => (button.textContent || '').includes(${JSON.stringify(text)}));
    if (!target) return false;
    target.click();
    return true;
  })()`
  const clicked = await waitFor(() => evaluate(client, expression), `button containing ${text}`)
  if (!clicked) throw new Error(`Could not click button containing ${text}`)
}

async function navigate(client, url, selector) {
  await client.send('Page.navigate', { url })
  await waitFor(
    async () => (await evaluate(client, 'document.readyState')) === 'complete',
    `page load ${url}`,
  )
  await waitForSelector(client, selector)
  await sleep(700)
}

async function setViewport(client, width, height) {
  await client.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
    screenWidth: width,
    screenHeight: height,
  })
  await sleep(250)
}

async function screenshot(client, name, width, height) {
  await setViewport(client, width, height)
  const capture = await client.send('Page.captureScreenshot', {
    format: 'png',
    fromSurface: true,
    captureBeyondViewport: false,
  })
  const path = `${outputDir}/${name}-${width}x${height}.png`
  await writeFile(path, Buffer.from(capture.data, 'base64'))
  console.log(`captured ${path}`)
}

await mkdir(outputDir, { recursive: true })
const chrome = resolveChrome()
console.log(`chrome=${chrome}`)

const browser = spawn(chrome, [
  '--headless=new',
  '--disable-gpu',
  '--no-sandbox',
  '--disable-dev-shm-usage',
  '--hide-scrollbars',
  '--force-device-scale-factor=1',
  '--window-size=1920,1080',
  `--remote-debugging-port=${debugPort}`,
  '--remote-debugging-address=127.0.0.1',
  'about:blank',
], { stdio: ['ignore', 'pipe', 'pipe'] })

browser.stderr.on('data', (chunk) => process.stderr.write(chunk))
browser.stdout.on('data', (chunk) => process.stdout.write(chunk))

let client
try {
  const target = await waitFor(async () => {
    const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`)
    if (!response.ok) return null
    const targets = await response.json()
    return targets.find((item) => item.type === 'page' && item.webSocketDebuggerUrl)
  }, 'Chrome DevTools target')

  client = new CdpClient(target.webSocketDebuggerUrl)
  await client.connect()
  await client.send('Page.enable')
  await client.send('Runtime.enable')
  await client.send('Log.enable')

  await navigate(client, `${baseUrl}/?view=login`, '.login-preview-page')
  await screenshot(client, 'login-preview', 1920, 1080)

  await navigate(client, `${baseUrl}/`, '.case-list-page')
  await screenshot(client, 'case-list', 1920, 1080)

  await clickButtonContaining(client, '新建询问')
  await waitForSelector(client, '.identity-modal')
  await sleep(500)
  await screenshot(client, 'identity-card', 1920, 1080)

  await navigate(client, `${baseUrl}/?caseId=${encodeURIComponent(caseId)}`, '.workspace')
  await clickButtonContaining(client, '审讯记录')
  await waitForSelector(client, '.template-interrogation-grid')
  await waitForSelector(client, '.formal-record-shell')
  await waitForSelector(client, '.live-dialogue-panel')
  await sleep(700)

  let fixtureSnapshot
  try {
    fixtureSnapshot = await waitFor(async () => {
      const snapshot = await inspectVisualFixture(client)
      return snapshot.complete ? snapshot : null
    }, 'populated formal template, raw ASR dialogue, and unmatched-question action card')
  } catch (error) {
    const diagnostic = await inspectVisualFixture(client)
    console.error(`kiosk-fixture-timeout-diagnostic=${JSON.stringify(diagnostic)}`)
    console.error(`browser-events-snapshot=${JSON.stringify(client.events.slice(-20))}`)
    throw error
  }
  console.log(`kiosk-fixture-ready=${JSON.stringify(fixtureSnapshot)}`)
  await screenshot(client, 'interrogation', 1920, 1080)
  await screenshot(client, 'interrogation', 1920, 900)
} finally {
  client?.close()
  browser.kill('SIGTERM')
  await sleep(300)
  if (!browser.killed) browser.kill('SIGKILL')
}