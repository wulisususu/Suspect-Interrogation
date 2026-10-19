import { afterEach, describe, expect, it } from 'vitest'
import { createCaseWithIdentity } from './interrogation'
import { saveIdentityProfileFacts } from './caseProfile'
import { LinuxHttpWsAdapter, resetRuntimeAdapterForTests } from '../runtime'

afterEach(() => resetRuntimeAdapterForTests())

describe('manual intake API contract', () => {
  it('sends the chosen type in the canonical backend field so its default cannot overwrite it', async () => {
    const requests: Record<string, unknown>[] = []
    resetRuntimeAdapterForTests(new LinuxHttpWsAdapter({ request: async (config) => {
      requests.push(config.data as Record<string, unknown>)
      return { data: { ok: true, data: { id: 'CASE-TEST', case_type: '诈骗' } } }
    } }))
    const result = await createCaseWithIdentity({ operatorId: '测试民警', officerName: '测试民警', caseType: '诈骗', identity: { name: '界面测试', source: 'MANUAL' } })
    expect(requests[0]).toMatchObject({ case_type: '诈骗', identity: { source: 'MANUAL' } })
    expect(result.caseType).toBe('诈骗')
  })

  it('waits for every fact request before reporting a partial save failure', async () => {
    let complete: (() => void) | undefined
    const slow = new Promise<void>((resolve) => { complete = resolve })
    const values: Record<string, unknown>[] = []
    resetRuntimeAdapterForTests(new LinuxHttpWsAdapter({ request: async (config) => {
      values.push(config.data as Record<string, unknown>)
      if (config.url.endsWith('/contact')) throw new Error('contact save failed')
      await slow
      return { data: { ok: true, data: config.data } }
    } }))
    let settled = false
    const saved = saveIdentityProfileFacts('CASE-TEST', { contact: '13800000000', current_address: '' }).then(() => { settled = true }, (cause) => { settled = true; return cause })
    await Promise.resolve()
    await Promise.resolve()
    expect(settled).toBe(false)
    complete?.()
    expect(await saved).toBeInstanceOf(Error)
    expect(values).toContainEqual({ value: '未录入', status: 'missing' })
  })
})
