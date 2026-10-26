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

  it('keeps the audio-source chip dark-on-light-text inside the navy top bar', () => {
    const chip = rule(workspaceSource, '.topbar-audio-source.voiceprint-source-banner')
    expect(chip).toMatch(/background:\s*rgba\(255, 255, 255, 0\.0\d\)/)
    expect(rule(workspaceSource, '.topbar-audio-source :deep(strong)')).toContain('color: var(--primary-100)')
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
