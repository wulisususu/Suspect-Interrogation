/** 后端建案未指定民警时写入的占位名，不是真实询问人。 */
export const PLACEHOLDER_OFFICER = '当前警官'

/**
 * 询问人 / 主审的显示名：占位值与空值一律视为未指定（走查 D38）。
 * 顶栏、正本、案件详情、台账都走这一条规则，同一案件各处显示保持一致。
 */
export function officerDisplayName(name?: string | null): string {
  const value = (name ?? '').trim()
  return value && value !== PLACEHOLDER_OFFICER ? value : ''
}
