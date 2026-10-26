import { describe, expect, it } from 'vitest'
import { parseRootRoute, rootRouteUrl } from './rootRoute'

describe('root route', () => {
  it('opens a case workspace when caseId is present', () => {
    expect(parseRootRoute('?caseId=C-1&view=settings')).toEqual({ page: 'case', caseId: 'C-1' })
  })

  it('maps view names to root pages and defaults to the lobby', () => {
    expect(parseRootRoute('')).toEqual({ page: 'home' })
    expect(parseRootRoute('?view=cases')).toEqual({ page: 'cases' })
    expect(parseRootRoute('?view=settings')).toEqual({ page: 'settings' })
    expect(parseRootRoute('?view=login')).toEqual({ page: 'login' })
    expect(parseRootRoute('?view=admin')).toEqual({ page: 'admin' })
    expect(parseRootRoute('?view=bogus')).toEqual({ page: 'home' })
  })

  it('reads admin sub-pages with their parameters', () => {
    expect(parseRootRoute('?view=admin-case&adminCaseId=C-9')).toEqual({ page: 'admin-case', adminCaseId: 'C-9' })
    expect(parseRootRoute('?view=admin-placeholder&panel=knowledge')).toEqual({ page: 'admin-placeholder', panel: 'knowledge' })
    expect(parseRootRoute('?view=admin-placeholder&panel=nope')).toEqual({ page: 'admin' })
    expect(parseRootRoute('?view=admin-case')).toEqual({ page: 'admin-cases' })
  })

  it('writes routes back while preserving unrelated query parameters', () => {
    const base = 'https://kiosk.local/app/?debug=1&view=cases'
    expect(rootRouteUrl(base, { page: 'case', caseId: 'C 1' })).toBe('https://kiosk.local/app/?debug=1&caseId=C+1')
    expect(rootRouteUrl(base, { page: 'home' })).toBe('https://kiosk.local/app/?debug=1')
    expect(rootRouteUrl(base, { page: 'admin-placeholder', panel: 'recordings' })).toBe('https://kiosk.local/app/?debug=1&view=admin-placeholder&panel=recordings')
    expect(rootRouteUrl('https://kiosk.local/?caseId=C-1&adminCaseId=X&panel=knowledge', { page: 'settings' })).toBe('https://kiosk.local/?view=settings')
  })
})
