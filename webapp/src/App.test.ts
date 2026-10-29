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

  it('renders the real knowledge base page for the knowledge panel instead of the placeholder', () => {
    expect(source).toContain("route.panel === 'knowledge'")
    expect(source).toContain('KnowledgeAdminView')
  })

  it('routes signature and recording panels to their real views', () => {
    expect(source).toContain("route.panel === 'signatures'")
    expect(source).toContain('OfficerSignatureAdminView')
    expect(source).toContain("route.panel === 'recordings'")
    expect(source).toContain('RecordingAdminView')
  })

  it('treats a successful login as entering the admin panel', () => {
    expect(source).toContain('@authenticated="openAdmin"')
    expect(source).not.toContain('@admin="openAdmin"')
  })
})
