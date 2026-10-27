/**
 * 当前操作人（询问人）标识 · 单一事实源
 *
 * 系统目前没有民警认证，能追溯到人的标识只有一个：案件里选定的询问人民警 ID
 * （来自声纹角色草稿 / 角色绑定）。审计记录必须写这个 ID，而不是"当前警官"
 * 这类占位文字——后者会让"全部操作留痕、可追溯到人"彻底失效。
 *
 * 认证接入后，这里换成登录态即可，调用方无需改动。
 */

let currentOfficerId: string | null = null

/** 更新当前操作人；传入空值表示"未知"，调用方不得自行编造替代值。 */
export function setCurrentOperator(officerId: string | null | undefined): void {
  const next = officerId == null ? '' : String(officerId).trim()
  currentOfficerId = next || null
}

/** 当前操作人 ID；未确定时返回 undefined，让后端把审计记为"未记录人员"。 */
export function currentOperatorId(): string | undefined {
  return currentOfficerId ?? undefined
}

/** 退出某个案件上下文时清空，避免把上一个案件的操作人带进下一个案件。 */
export function resetCurrentOperator(): void {
  currentOfficerId = null
}
