import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import type { Officer } from '../api/officers'
import OfficerSelect from './OfficerSelect.vue'
import intakeSource from './IdentityIntakeModal.vue?raw'
import manualSource from './ManualIdentityFields.vue?raw'

const officer = (badgeNumber: string, name: string): Officer => ({ badgeNumber, name, unit: '城东派出所', enabled: true, isAdmin: false, displayName: name })
const officers = [officer('038291', '张伟'), officer('038292', '李明')]
const render = async (props: Record<string, unknown>) =>
  (await renderToString(createSSRApp(OfficerSelect, props))).replace(/<!--[\s\S]*?-->/g, '')

describe('OfficerSelect', () => {
  it('lists roster officers with badge numbers and blocks the one holding the other role', async () => {
    const html = await render({ name: '', badge: '', officers, available: true, exclude: '038291', placeholder: '请选择记录民警' })
    expect(html).toContain('<select')
    expect(html).toContain('请选择记录民警')
    expect(html).toContain('李明（038292）')
    expect(html).toMatch(/<option value="038291" disabled[^>]*>\s*张伟（038291） · 已担任另一角色/)
  })

  it('falls back to typing a name when the roster is unavailable', async () => {
    const html = await render({ name: '王警官', badge: '', officers: [], available: false, placeholder: '请选择主审民警' })
    expect(html).not.toContain('<select')
    expect(html).toContain('value="王警官"')
    expect(html).toContain('placeholder="请填写主审民警"')
  })
})

describe('new inquiry dialog', () => {
  it('puts both officers first and keeps only the basic identity fields', () => {
    expect(intakeSource.indexOf('class="officer-band"')).toBeLessThan(intakeSource.indexOf('<template v-if="mode === \'card\'">'))
    expect(intakeSource).toContain('v-model:badge="form.officerBadge"')
    expect(intakeSource).toContain('v-model:badge="form.recorderBadge"')
    expect(intakeSource).toContain('bindCaseOfficers(caseId, form.officerBadge, form.recorderBadge)')
    for (const later of ['interrogationPlace', 'peoplesRepresentative', 'contact', 'currentAddress', 'householdRegistration', 'interrogationRound']) {
      expect(manualSource).not.toContain(`form.${later}`)
    }
  })
})
