import type { FormalQuestionSection } from '../types/templateInterrogation'

/** 追加一问的插入点：最后一张非固定结尾（CLOSING）的题卡。
 *
 * 固定结尾是法定程式（补充陈述、属实确认、签字捺印），动态问题只能插在正文段，
 * 后端对 after=CLOSING 会直接拒绝（FIXED_SECTION_BOUNDARY，实测 AAC708 模板
 * 最后一张卡就是结尾题，按住说话每次都报错）。返回 null 表示交给后端落到正文
 * 末尾（add_case_question 对 after=None 的默认行为）。 */
export function lastInsertableCardId(cards: { id: string; sectionType: FormalQuestionSection }[]): string | null {
  for (let index = cards.length - 1; index >= 0; index -= 1) {
    if (cards[index].sectionType !== 'CLOSING') return cards[index].id
  }
  return null
}
