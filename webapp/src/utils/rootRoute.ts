/**
 * 根页面路由：一体机没有 vue-router，页面状态记在查询参数里（view / caseId / mode / adminCaseId / panel / next），
 * 用 replaceState 写回，刷新后回到同一页；与页面无关的查询参数原样保留。
 */
export const ADMIN_PANELS = ['knowledge', 'templates', 'template-edit', 'signatures', 'recordings'] as const
export type AdminPanel = typeof ADMIN_PANELS[number]

/** 民警验证身份后要去的地方：大厅两种办理模式，或右上角管理面板。 */
export const LOGIN_TARGETS = ['manual', 'self', 'admin'] as const
export type LoginTarget = typeof LOGIN_TARGETS[number]

export type RootRoute =
  | { page: 'home' | 'cases' | 'admin' | 'admin-cases' | 'admin-pending' | 'admin-audit' }
  | { page: 'login'; next?: LoginTarget }
  /** selfService：自助模式（当事人本人作答），地址栏记为 mode=self，刷新后仍停在自助页面 */
  | { page: 'case'; caseId: string; selfService?: boolean }
  | { page: 'admin-case'; adminCaseId: string }
  /** recordingCaseId：从案件详情跳进录音管理时预选该案件 */
  | { page: 'admin-placeholder'; panel: AdminPanel; recordingCaseId?: string }

const SIMPLE_PAGES = ['cases', 'admin', 'admin-cases', 'admin-pending', 'admin-audit'] as const

export function parseRootRoute(search: string): RootRoute {
  const params = new URLSearchParams(search)
  const caseId = params.get('caseId')
  if (caseId) return params.get('mode') === 'self' ? { page: 'case', caseId, selfService: true } : { page: 'case', caseId }
  const view = params.get('view') || ''
  if (view === 'login') {
    const next = params.get('next') as LoginTarget | null
    return next && LOGIN_TARGETS.includes(next) ? { page: 'login', next } : { page: 'login' }
  }
  if (view === 'admin-case') {
    const adminCaseId = params.get('adminCaseId')
    return adminCaseId ? { page: 'admin-case', adminCaseId } : { page: 'admin-cases' }
  }
  if (view === 'admin-placeholder') {
    const panel = params.get('panel') as AdminPanel | null
    if (!panel || !ADMIN_PANELS.includes(panel)) return { page: 'admin' }
    const recordingCaseId = params.get('recordingCaseId') || undefined
    return recordingCaseId ? { page: 'admin-placeholder', panel, recordingCaseId } : { page: 'admin-placeholder', panel }
  }
  const simple = SIMPLE_PAGES.find((page) => page === view)
  return simple ? { page: simple } : { page: 'home' }
}

export function rootRouteUrl(current: string, route: RootRoute): string {
  const next = new URL(current)
  for (const key of ['view', 'caseId', 'mode', 'adminCaseId', 'panel', 'next', 'recordingCaseId']) next.searchParams.delete(key)
  if (route.page === 'case') {
    next.searchParams.set('caseId', route.caseId)
    if (route.selfService) next.searchParams.set('mode', 'self')
  } else if (route.page !== 'home') next.searchParams.set('view', route.page)
  if (route.page === 'login' && route.next) next.searchParams.set('next', route.next)
  if (route.page === 'admin-case') next.searchParams.set('adminCaseId', route.adminCaseId)
  if (route.page === 'admin-placeholder') {
    next.searchParams.set('panel', route.panel)
    if (route.recordingCaseId) next.searchParams.set('recordingCaseId', route.recordingCaseId)
  }
  return next.toString()
}
