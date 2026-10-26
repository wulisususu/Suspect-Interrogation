import { describe, expect, it } from 'vitest'
import source from './InterrogationWorkspace.vue?raw'

describe('interrogation workspace shell', () => {
  it('does not render the device capability and fingerprint action module', () => {
    expect(source).not.toContain("import DeviceStatusBar from '../components/DeviceStatusBar.vue'")
    expect(source).not.toContain('<DeviceStatusBar />')
  })

  it('drives every page from a single step bar instead of parallel tabs', () => {
    // 旧结构：工作区 5 个并列 tab + 笔录页内部 3 个 tab，这里确保两套都已被移除。
    expect(source).not.toContain('workspace-page-tabs')
    expect(source).not.toContain('record-mode-tabs')
    expect(source).toContain('<StepBar')
    expect(source).toContain(':steps="FLOW_STEPS"')
    expect(source).toContain(':current="flowStep"')
  })

  it('places session actions inside the step bar actions slot', () => {
    const stepBar = source.indexOf('<StepBar')
    const controls = source.indexOf('<SessionControls')
    const content = source.indexOf('<section class="workspace-page-body"')

    expect(stepBar).toBeGreaterThanOrEqual(0)
    expect(controls).toBeGreaterThan(stepBar)
    expect(controls).toBeLessThan(content)
    expect(source).not.toContain(':stage-text="store.stageText"')
  })

  it('shows the case identity in a top bar chip and keeps officer metadata beside it', () => {
    expect(source).toContain('案 {{ store.caseSummary.id || store.caseId }}')
    expect(source).toContain('询问人 {{ store.caseSummary.officerName ||')
    expect(source).toContain('记录人 {{ recorderName }}')
    expect(source).not.toContain('对象：')
    expect(source).not.toContain('class="state-chip"')
  })

  it('renders the compact audio source banner inside the dark top bar', () => {
    const topbarStart = source.indexOf('<header class="app-topbar"')
    const topbarEnd = source.indexOf('</header>')
    const banner = source.indexOf('<VoiceprintAudioSourceBanner')

    expect(topbarStart).toBeGreaterThanOrEqual(0)
    expect(banner).toBeGreaterThan(topbarStart)
    expect(topbarEnd).toBeGreaterThan(banner)
    expect(source).toContain('class="topbar-audio-source"')
    expect(source).not.toContain('class="session-audio-source"')
  })

  it('keeps MOSS transcription as a top bar tool rather than a workflow step', () => {
    expect(source).toContain("activePage = 'moss'")
    expect(source).toContain('MOSS 转写')
  })
})
