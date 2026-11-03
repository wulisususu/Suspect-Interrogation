import { describe, expect, it } from 'vitest'
import type { CheckRule } from '../api/knowledge'
import { checkRuleSource, knowledgeChecks } from './knowledgeChecks'
import { finalizeChecks } from './reviewChecks'

const ebikeRule: CheckRule = {
  entryId: 'e1', title: '盗窃电动车笔录定稿校验', version: 2, status: 'verified', origin: 'vault',
  categoryName: '定稿校验规则', sourceRef: null, sourcePath: 'rules/rule-theft-ebike.md', vaultUid: 'rule-theft-ebike',
  matchedBy: { scope: 'TEMPLATE', value: 'THEFT_EBIKE_V1' },
  items: [
    { key: 'e1#0', label: '锁具情况', terms: ['锁', 'U型锁'], elementKey: 'lock' },
    { key: 'e1#1', label: '购买凭证', terms: ['发票', '收据', '购买凭证', '付款记录'], elementKey: null },
    { key: 'e1#2', label: '车辆价值', terms: ['价值', '元'], elementKey: 'value' },
  ],
}

describe('knowledgeChecks', () => {
  it('passes an item when the formal answers mention any of its terms, ignoring whitespace', () => {
    const checks = knowledgeChecks([ebikeRule], [
      { active: true, formalAnswerText: '车停在楼下，用 U 型 锁锁着。' },
      { active: true, formalAnswerText: '' },
    ])
    expect(checks.map((item) => [item.title, item.state])).toEqual([
      ['锁具情况', 'pass'], ['购买凭证', 'pending'], ['车辆价值', 'pending'],
    ])
    expect(checks[0].detail).toBe('正本已记录「锁」')
    expect(checks[1].detail).toBe('正本中未见「发票、收据、购买凭证」等表述，可补问或如实记为未获取')
    expect(checks.every((item) => item.source === '知识库《盗窃电动车笔录定稿校验》v2 · rules/rule-theft-ebike.md')).toBe(true)
  })

  it('counts a confirmed linked element and ignores inactive questions', () => {
    const checks = knowledgeChecks([ebikeRule], [
      { active: false, formalAnswerText: '有发票。' },
      { active: true, formalAnswerText: '买的时候花了三千。' },
    ], [{ key: 'value', label: '车辆价值与发票凭证', value: '三千元', status: 'confirmed' }])
    expect(checks.find((item) => item.title === '购买凭证')?.state).toBe('pending')
    expect(checks.find((item) => item.title === '车辆价值')).toMatchObject({ state: 'pass', detail: '要素「车辆价值与发票凭证」已确认' })
  })

  it('falls back to the source ref when the entry has no vault path', () => {
    expect(checkRuleSource({ title: '手工规则', version: 1, sourcePath: null, sourceRef: '《询问规范》第 3 条' }))
      .toBe('知识库《手工规则》v1 · 《询问规范》第 3 条')
    expect(checkRuleSource({ title: '手工规则', version: 3, sourcePath: null, sourceRef: null })).toBe('知识库《手工规则》v3')
  })

  it('appends rule checks to the finalize list as hints with their source', () => {
    const list = finalizeChecks({
      summary: { suspectName: '王某某', idNumber: '330501199205142319' }, templateTitle: '盗窃（电动车）', autoChecks: [],
      draftAnswers: 1, unresolvedFragments: 0, unresolvedQa: 0,
      knowledgeChecks: knowledgeChecks([ebikeRule], [{ formalAnswerText: '有购车发票' }]),
    })
    expect(list.map((item) => item.key)).toEqual(['template', 'identity', 'kb:e1#0', 'kb:e1#1', 'kb:e1#2', 'drafts'])
    expect(list.find((item) => item.key === 'kb:e1#1')).toMatchObject({ state: 'pass', source: '知识库《盗窃电动车笔录定稿校验》v2 · rules/rule-theft-ebike.md' })
    expect(list.some((item) => item.state === 'block')).toBe(false)
  })
})
