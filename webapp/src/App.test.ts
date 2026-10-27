import { describe, expect, it } from 'vitest'
import source from './App.vue?raw'

describe('root navigation query handling', () => {
  it('routes through the tested root-route helpers instead of ad hoc query edits', () => {
    expect(source).toContain('parseRootRoute(location.search)')
    expect(source).toContain('rootRouteUrl(location.href, next)')
    expect(source).toContain('history.replaceState')
  })

  it('exposes the global officer voiceprint library outside a case', () => {
    expect(source).toContain('SystemSettingsView')
    expect(source).toContain('@voiceprints="openSettings"')
  })
})
