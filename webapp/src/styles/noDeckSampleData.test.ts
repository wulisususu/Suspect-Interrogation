import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')
const files = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const full = join(dir, name)
  if (statSync(full).isDirectory()) return files(full)
  return /\.(vue|ts)$/.test(name) && !name.endsWith('.test.ts') ? [full] : []
})

describe('design deck sample data stays out of the product', () => {
  it('contains no badge numbers, case numbers or names from the deck', () => {
    const hits = files(SRC).filter((file) => /038291|036612|2026-0428|张伟（/.test(readFileSync(file, 'utf8')))
    expect(hits).toEqual([])
  })
})
