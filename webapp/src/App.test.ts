import { describe, expect, it } from 'vitest'
import source from './App.vue?raw'

describe('root navigation query handling', () => {
  it('routes through the tested root-route helpers instead of ad hoc query edits', () => {
    expect(source).toContain('parseRootRoute(location.search)')
    expect(source).toContain('rootRouteUrl(location.href, next)')
    expect(source).toContain('history.replaceState')
  })

  it('no longer exposes the officer voiceprint library now that voiceprints left the workflow', () => {
    expect(source).not.toContain('SystemSettingsView')
    expect(source).not.toContain('@voiceprints')
  })
})
