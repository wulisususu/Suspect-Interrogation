import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./FormalTemplatePanel.vue', import.meta.url), 'utf8')

describe('FormalTemplatePanel SFC boundary', () => {
  it('keeps scoped styles outside the template block', () => {
    const templateClose = source.indexOf('</template>')
    const scopedStyleOpen = source.indexOf('<style scoped>')

    expect(templateClose).toBeGreaterThan(-1)
    expect(scopedStyleOpen).toBeGreaterThan(-1)
    expect(templateClose).toBeLessThan(scopedStyleOpen)
  })
})

describe('FormalTemplatePanel header fields', () => {
  it('edits the current address fact, not the ID-card address on the case', () => {
    const line = source.split('\n').find((item) => item.includes('aria-label="现住址"')) ?? ''

    // 纸面文书用的是 current_address，编辑器必须读写同一个字段。
    expect(line).toContain("factText('current_address')")
    expect(line).toContain("saveHeader($event, 'fact', 'current_address')")
    expect(line).not.toContain('summary.address')
  })
})
