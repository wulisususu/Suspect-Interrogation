import { describe, expect, it } from 'vitest'
import dialogueSource from './LiveDialoguePanel.vue?raw'
import dialogueCss from './templateInterrogation.css?raw'

const apiModules = import.meta.glob('../api/*.ts')

describe('solo-testing BOT is removed', () => {
  it('has no BOT logic or button in the live dialogue panel', () => {
    expect(dialogueSource).not.toMatch(/\b(?:bot|BOT)(?![a-z])|devBot|dev-bot/)
  })

  it('ships no BOT styles or API client', () => {
    expect(dialogueCss).not.toContain('.bot-toggle')
    expect(Object.keys(apiModules).filter((path) => /devBot/i.test(path))).toEqual([])
  })
})
