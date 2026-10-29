import { describe, expect, it } from 'vitest'
import appSource from '../App.vue?raw'
import dashboardSource from './CaseDashboardView.vue?raw'
import loginSource from './LoginView.vue?raw'

describe('PDF phase-one frontend redesign', () => {
  it('keeps the existing case workspace reachable and exposes login as preview-only route', () => {
    expect(appSource).toContain('<InterrogationWorkspace v-if="route.page === \'case\'"')
    expect(appSource).toContain('<LoginView v-else-if="route.page === \'login\'"')
    expect(appSource).toContain('CaseDashboardView')
  })

  it('builds the ledger from actual loaded API rows', () => {
    expect(dashboardSource).toContain('fetchCases(query ? 100 : 50, query)')
    expect(dashboardSource).toContain('ledgerActions(')
    expect(dashboardSource).toContain('filteredCases.value.slice(')
    expect(dashboardSource).not.toContain('fetchRuntimeCapabilities')
  })

  it('authenticates against the backend session instead of faking a frontend check', () => {
    expect(loginSource).toContain('type="password"')
    expect(loginSource).toContain('loginOfficer(')
    expect(loginSource).toContain('fetchAuthSession')
    expect(loginSource).not.toContain('尚未接入警号密码认证接口')
    expect(loginSource).not.toContain('localStorage')
    expect(loginSource).not.toContain('sessionStorage')
  })
})
