import { describe, expect, it } from 'vitest'
import dashboardSource from './CaseDashboardView.vue?raw'
import workspaceSource from './InterrogationWorkspace.vue?raw'
import filterSource from '../components/FilterSelect.vue?raw'

function rule(source: string, selector: string) {
  const start = source.indexOf(`\n${selector} {`)
  return start < 0 ? '' : source.slice(start, source.indexOf('}', start) + 1)
}

describe('visual defects found in the design review', () => {
  it('lets a single case row keep its natural height', () => {
    expect(rule(dashboardSource, '.case-dashboard-table')).not.toMatch(/height:\s*100%/)
  })

  it('keeps the top bar meta light-on-navy', () => {
    expect(rule(workspaceSource, '.case-chip')).toContain('color: var(--primary-100)')
    expect(rule(workspaceSource, '.topbar-clock')).toContain('color: var(--surface)')
  })

  it('keeps every workspace template line readable', () => {
    const template = workspaceSource.slice(workspaceSource.indexOf('<template>'), workspaceSource.indexOf('<style'))
    expect(template.split('\n').filter((line) => line.length > 240)).toEqual([])
  })

  it('marks filter list items as presentational inside the listbox', () => {
    const items = filterSource.match(/<li\b[^>]*>/g) ?? []
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) expect(item).toContain('role="none"')
  })
})

describe('dictation step header', () => {
  it('shows the selected template on the step bar while dictating (定稿 lives in the page header)', () => {
    expect(workspaceSource).toContain('`已选模板：${templateTitle.value || caseTypeText.value}`')
    expect(workspaceSource).not.toContain('step-finalize')
  })
})

describe('workspace print output', () => {
  it('keeps the workspace chrome off the printed record', () => {
    for (const tag of ['<header class="app-topbar', '<StepBar', '<div class="workspace-toast-region']) {
      const start = workspaceSource.indexOf(tag)
      expect(start, tag).toBeGreaterThan(0)
      expect(workspaceSource.slice(start, workspaceSource.indexOf('>', start)), tag).toContain('record-no-print')
    }
  })
})

import stepBarSource from '../components/StepBar.vue?raw'

describe('step bar on 1280px screens', () => {
  it('collapses non-current step titles to numbers but keeps their accessible names', () => {
    expect(stepBarSource).toMatch(/@media \(max-width: 1440px\)[\s\S]*\.step-button:not\(\.is-active\) \.step-title\s*\{\s*display: none;/)
    expect(stepBarSource).toContain(':aria-label="step.title"')
  })
})
