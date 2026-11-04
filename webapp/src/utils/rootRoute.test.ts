import { describe, expect, it } from 'vitest'
import { parseRootRoute, rootRouteUrl } from './rootRoute'

describe('root route', () => {
  it('opens a case workspace when caseId is present', () => {
    expect(parseRootRoute('?caseId=C-1&view=settings')).toEqual({ page: 'case', caseId: 'C-1' })
  })

  it('maps view names to root pages and defaults to the lobby', () => {
    expect(parseRootRoute('')).toEqual({ page: 'home' })
    expect(parseRootRoute('?view=cases')).toEqual({ page: 'cases' })
    expect(parseRootRoute('?view=login')).toEqual({ page: 'login' })
    expect(parseRootRoute('?view=settings')).toEqual({ page: 'home' })
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

  it('keeps the self-service mode and the post-login target across refreshes', () => {
    expect(parseRootRoute('?caseId=C-1&mode=self')).toEqual({ page: 'case', caseId: 'C-1', selfService: true })
    expect(parseRootRoute('?caseId=C-1&mode=other')).toEqual({ page: 'case', caseId: 'C-1' })
    expect(parseRootRoute('?view=login&next=self')).toEqual({ page: 'login', next: 'self' })
    expect(parseRootRoute('?view=login&next=nope')).toEqual({ page: 'login' })
    const base = 'https://kiosk.local/?view=login&next=self'
    expect(rootRouteUrl(base, { page: 'case', caseId: 'C-1', selfService: true })).toBe('https://kiosk.local/?caseId=C-1&mode=self')
    expect(rootRouteUrl('https://kiosk.local/?caseId=C-1&mode=self', { page: 'case', caseId: 'C-1' })).toBe('https://kiosk.local/?caseId=C-1')
    expect(rootRouteUrl('https://kiosk.local/', { page: 'login', next: 'manual' })).toBe('https://kiosk.local/?view=login&next=manual')
  })

  it('writes routes back while preserving unrelated query parameters', () => {
    const base = 'https://kiosk.local/app/?debug=1&view=cases'
    expect(rootRouteUrl(base, { page: 'case', caseId: 'C 1' })).toBe('https://kiosk.local/app/?debug=1&caseId=C+1')
    expect(rootRouteUrl(base, { page: 'home' })).toBe('https://kiosk.local/app/?debug=1')
    expect(rootRouteUrl(base, { page: 'admin-placeholder', panel: 'recordings' })).toBe('https://kiosk.local/app/?debug=1&view=admin-placeholder&panel=recordings')
    expect(rootRouteUrl('https://kiosk.local/?caseId=C-1&adminCaseId=X&panel=knowledge', { page: 'login' })).toBe('https://kiosk.local/?view=login')
  })
})
