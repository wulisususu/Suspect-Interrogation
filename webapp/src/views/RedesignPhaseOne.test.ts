import { describe, expect, it } from 'vitest'
import appSource from '../App.vue?raw'
import dashboardSource from './CaseDashboardView.vue?raw'
import loginSource from './LoginView.vue?raw'

describe('PDF phase-one frontend redesign', () => {
  it('keeps the existing case workspace reachable and exposes login as preview-only route', () => {
    expect(appSource).toContain('InterrogationWorkspace v-if="caseId"')
    expect(appSource).toContain("params.get('view') === 'login'")
    expect(appSource).toContain('LoginView v-else-if')
    expect(appSource).toContain('CaseDashboardView')
  })

  it('builds case counts and workflow labels from actual loaded API rows', () => {
    expect(dashboardSource).toContain('fetchCases(query ? 100 : 50, query)')
    expect(dashboardSource).toContain('workflowState')
    expect(dashboardSource).toContain("workflow === 'REPORT_GENERATED'")
    expect(dashboardSource).toContain('filteredCases.value.slice(')
    expect(dashboardSource).toContain('fetchRuntimeCapabilities(true)')
    expect(dashboardSource).toContain('fetchOfficerVoiceProfiles(true)')
  })

  it('does not pretend a frontend-only credential form is an authentication boundary', () => {
    expect(loginSource).toContain('type="password"')
    expect(loginSource).toContain('尚未接入警号密码认证接口')
    expect(loginSource).toContain('前端预览模式')
    expect(loginSource).not.toContain('localStorage')
    expect(loginSource).not.toContain('sessionStorage')
  })
})
