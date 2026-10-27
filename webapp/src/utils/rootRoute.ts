/**
 * 根页面路由：一体机没有 vue-router，页面状态记在查询参数里（view / caseId / adminCaseId / panel），
 * 用 replaceState 写回，刷新后回到同一页；与页面无关的查询参数原样保留。
 */
export const ADMIN_PANELS = ['knowledge', 'templates', 'template-edit', 'signatures', 'recordings'] as const
export type AdminPanel = typeof ADMIN_PANELS[number]

export type RootRoute =
  | { page: 'home' | 'cases' | 'settings' | 'login' | 'admin' | 'admin-cases' | 'admin-pending' | 'admin-audit' }
  | { page: 'case'; caseId: string }
  | { page: 'admin-case'; adminCaseId: string }
  | { page: 'admin-placeholder'; panel: AdminPanel }

const SIMPLE_PAGES = ['cases', 'settings', 'login', 'admin', 'admin-cases', 'admin-pending', 'admin-audit'] as const

export function parseRootRoute(search: string): RootRoute {
  const params = new URLSearchParams(search)
  const caseId = params.get('caseId')
  if (caseId) return { page: 'case', caseId }
  const view = params.get('view') || ''
  if (view === 'admin-case') {
    const adminCaseId = params.get('adminCaseId')
    return adminCaseId ? { page: 'admin-case', adminCaseId } : { page: 'admin-cases' }
  }
  if (view === 'admin-placeholder') {
    const panel = params.get('panel') as AdminPanel | null
    return panel && ADMIN_PANELS.includes(panel) ? { page: 'admin-placeholder', panel } : { page: 'admin' }
  }
  const simple = SIMPLE_PAGES.find((page) => page === view)
  return simple ? { page: simple } : { page: 'home' }
}

export function rootRouteUrl(current: string, route: RootRoute): string {
  const next = new URL(current)
  for (const key of ['view', 'caseId', 'adminCaseId', 'panel']) next.searchParams.delete(key)
  if (route.page === 'case') next.searchParams.set('caseId', route.caseId)
  else if (route.page !== 'home') next.searchParams.set('view', route.page)
  if (route.page === 'admin-case') next.searchParams.set('adminCaseId', route.adminCaseId)
  if (route.page === 'admin-placeholder') next.searchParams.set('panel', route.panel)
  return next.toString()
}
