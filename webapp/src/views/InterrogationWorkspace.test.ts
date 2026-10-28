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

  it('keeps the step bar free of session buttons (design: ③ cards start / pause, ④ 确认定稿 ends the session)', () => {
    expect(source).not.toContain('<SessionControls')
    expect(source).not.toContain(':stage-text="store.stageText"')
    expect(source).toContain('@toggle-pause="store.togglePause"')
  })

  it('shows the case identity in a top bar chip and keeps officer metadata beside it', () => {
    expect(source).toContain('`案 ${store.caseSummary.id || store.caseId}`')
    expect(source).toContain('<span class="case-chip">{{ caseChip }}</span>')
    expect(source).toContain('询问人 {{ officerText }}')
    expect(source).toContain('记录人 {{ recorderName }}')
    expect(source).not.toContain('对象：')
    expect(source).not.toContain('class="state-chip"')
  })

  it('matches the design top bar: status and clock on the right, no tool buttons', () => {
    const topbar = source.slice(source.indexOf('<header class="app-topbar'), source.indexOf('</header>'))
    expect(topbar).toContain('{{ statusText }}')
    expect(topbar).toContain('{{ clockText }}')
    for (const removed of ['VoiceprintAudioSourceBanner', 'MOSS 转写', 'AiSettingsPanel']) expect(topbar).not.toContain(removed)
  })

  it('keeps intake on a single page without voiceprint or preparation sub-pages', () => {
    expect(source).not.toContain('intake-subnav')
    expect(source).not.toContain('VoiceprintSetupPage')
    expect(source).not.toContain('CasePreparationPage')
    expect(source).toContain("v-else-if=\"activePage === 'profile'\"")
  })
})

describe('record header editing', () => {
  it('patches the header in place instead of reloading the whole workspace', () => {
    const start = source.indexOf('async function saveRecordHeader')
    const end = source.indexOf('async function correctRecognitionFragment')
    const body = source.slice(start, end)

    expect(start).toBeGreaterThan(-1)
    expect(end).toBeGreaterThan(start)
    // 抬头保存只影响本页显示；重新 initialize 会让页面闪一下并冲掉其它未保存输入。
    expect(body).not.toContain('await refreshCaseWorkspace()')
    expect(body).toContain('store.caseSummary =')
    expect(body).toContain('store.facts')
  })
})
