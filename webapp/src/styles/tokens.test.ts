import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return /\.(vue|css)$/.test(name) ? [full] : []
  })
}

function styleText(file: string) {
  const text = readFileSync(file, 'utf8')
  if (!file.endsWith('.vue')) return text
  return [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((match) => match[1]).join('\n')
}

/** Every `selector { declarations }` block, flattened out of @media wrappers. */
function ruleBlocks(css: string) {
  return [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((match) => ({ selector: match[1]!.trim(), body: match[2]! }))
}

function declaredToken(body: string, property: 'color' | 'background' | 'background-color') {
  const match = body.match(new RegExp(`(?:^|;|\\s)${property}\\s*:\\s*var\\((--[a-z0-9-]+)\\)\\s*(?:;|$)`))
  return match?.[1]
}

const files = sourceFiles(SRC).filter((file) => !file.endsWith('tokens.css'))

describe('design tokens', () => {
  it('never paints text in the same token as its own background', () => {
    const invisible: string[] = []
    for (const file of files) {
      for (const { selector, body } of ruleBlocks(styleText(file))) {
        const color = declaredToken(body, 'color')
        const background = declaredToken(body, 'background') ?? declaredToken(body, 'background-color')
        if (color && color === background) invisible.push(`${file.replace(SRC, 'src')}: ${selector} → ${color}`)
      }
    }
    expect(invisible).toEqual([])
  })

  it('takes the font stack from tokens.css only', () => {
    const rootBlocks = ruleBlocks(readFileSync(join(SRC, 'styles.css'), 'utf8')).filter((block) => block.selector === ':root')
    expect(rootBlocks.some((block) => /font-family/.test(block.body))).toBe(false)
  })

  it('keeps the formal record paper on paper tokens', () => {
    const tokens = readFileSync(join(SRC, 'styles/tokens.css'), 'utf8')
    for (const name of ['--paper-bg', '--paper-ink', '--paper-rule', '--paper-muted']) expect(tokens).toContain(`${name}:`)
    for (const file of ['components/RecordSigningPage.vue', 'components/RecordArchivePage.vue', 'components/FormalTemplatePanel.vue']) {
      expect(styleText(join(SRC, file)).match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([])
    }
  })
})
