import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import CasePreparationPage from './CasePreparationPage.vue'
import { capabilitySet } from '../runtime/types'

const summary = { id: 'CASE-1', suspectName: '测试人员', officerName: '民警', state: 'DRAFT', stage: 'IDENTITY', identitySource: 'MANUAL', idNumber: '330100198001010011' }
const readiness = { suspectReady: true, canStart: true, interrogatorReady: false, recorderReady: false, recognitionMode: 'SUSPECT_ONLY' }

async function screen(overrides = {}) {
  return renderToString(createSSRApp(CasePreparationPage, {
    summary, facts: [], readiness, enrollmentState: { phase: 'IDLE' },
    capabilities: capabilitySet('AVAILABLE'), sessionStatus: 'READY', recorderName: '未指定',
    ...overrides,
  }))
}

describe('preparation start conditions', () => {
  it('allows manual identity intake without requiring an available card reader', async () => {
    const capabilities = capabilitySet('AVAILABLE')
    capabilities.identity.state = 'NOT_CONFIGURED'
    const html = await screen({ capabilities })
    expect(html).toContain('人工录入')
    expect(html).not.toMatch(/<button[^>]*disabled[^>]*>开始审讯/)
    expect(html).toContain('三项准备已就绪')
  })

  it('does not unlock start when backend readiness or speech service is unavailable', async () => {
    const noVoiceprint = await screen({ readiness: { ...readiness, canStart: false } })
    expect(noVoiceprint).toMatch(/<button[^>]*disabled[^>]*>开始审讯/)
    const capabilities = capabilitySet('AVAILABLE')
    capabilities.asr.state = 'ERROR'
    const noSpeech = await screen({ capabilities })
    expect(noSpeech).toMatch(/<button[^>]*disabled[^>]*>开始审讯/)
    expect(noSpeech).toContain('语音识别服务')
  })

  it('requires recorded identity and does not label missing data as verified', async () => {
    const html = await screen({ summary: { ...summary, suspectName: '', idNumber: '', identitySource: '' } })
    expect(html).toMatch(/<button[^>]*disabled[^>]*>开始审讯/)
    expect(html).toContain('待补充')
    expect(html).not.toContain('身份核验 · 已通过')
  })

  it('keeps a simulated enrollment locked and uses usable speech for progress', async () => {
    const html = await screen({
      readiness: { ...readiness, suspectReady: false, canStart: false, simulated: true },
      enrollmentState: { phase: 'RECORDING', kind: 'SUSPECT', capturedDurationMs: 59000, usableSpeechMs: 12000, targetDurationMs: 60000 },
    })
    expect(html).toContain('12 秒 / 60 秒')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>开始审讯/)
  })

  it('never offers a second start for an existing session and shows its actual phase', async () => {
    const html = await screen({ sessionStatus: 'RUNNING' })
    expect(html).toContain('2 审讯 · 当前')
    expect(html).toContain('进入审讯工作台')
    expect(html).not.toContain('>开始审讯')
  })

  it('blocks even registered voiceprints while an enrollment is still processing', async () => {
    const html = await screen({ enrollmentState: { phase: 'PROCESSING' } })
    expect(html).toMatch(/<button[^>]*disabled[^>]*>开始审讯/)
    expect(html).toContain('请先完成当前声纹采集')
  })
})
