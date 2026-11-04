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

  it('continues to the entry the officer picked after login, admin panel by default', () => {
    expect(source).toContain('@authenticated="afterLogin(route.next)"')
    expect(source).toContain("if (target === 'admin') openAdmin()")
    expect(source).not.toContain('@admin="openAdmin"')
  })

  it('gates both lobby modes behind the officer login and opens self-service cases in their own workspace', () => {
    expect(source).toContain('<KioskHomeView v-else-if="route.page === \'home\'" @enter="enter" />')
    expect(source).toContain('if (await officerSessionActive()) afterLogin(target)')
    expect(source).toContain("go({ page: 'login', next: target })")
    expect(source).toContain('v-if="route.page === \'case\' && route.selfService"')
    expect(source).toContain('@handover="openCase(route.caseId)"')
  })
})
