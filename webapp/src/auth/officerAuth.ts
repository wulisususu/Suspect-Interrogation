import { ref } from 'vue'

/**
 * 民警会话失效的统一出口
 *
 * 后端在会话过期 / 未验证时返回 401 AUTH_SESSION_REQUIRED，面板被锁时返回 423 AUTH_SESSION_LOCKED。
 * 这里把它们收敛成一个「需要重新验证」的提示：App 根据 authPrompt 叠加验证弹窗，
 * 不卸载当前办案页面，正在录音的浏览器音频继续写入本地缓存，验证通过后自动续传。
 */

export type OfficerAuthReason = 'required' | 'locked'

export interface OfficerAuthPrompt {
  reason: OfficerAuthReason
}

export const authPrompt = ref<OfficerAuthPrompt | null>(null)

/**
 * 是否允许由接口失败自动弹出验证。大厅与民警验证页上的后台请求（如未完成案件计数）
 * 失败属正常现象，不应在公共大厅自动弹窗；那里只由「开始新建笔录」等明确操作发起验证。
 */
export const autoPromptEnabled = ref(true)

const waiters: Array<(ok: boolean) => void> = []

const AUTH_REQUIRED_CODES = new Set(['AUTH_SESSION_REQUIRED', 'AUTH_REAUTHENTICATION_REQUIRED'])
const AUTH_LOCKED_CODES = new Set(['AUTH_SESSION_LOCKED'])

/** 后端错误码 → 需要的验证类型；与会话无关的错误（如密码错误）返回 null。 */
export function authReasonForError(status: number | undefined, code: string | undefined): OfficerAuthReason | null {
  if (status === 423 || (code && AUTH_LOCKED_CODES.has(code))) return 'locked'
  if (status === 401 && code && AUTH_REQUIRED_CODES.has(code)) return 'required'
  return null
}

/** 打开（或沿用已打开的）验证弹窗，验证通过时 resolve(true)，取消时 resolve(false)。 */
export function requestOfficerAuth(reason: OfficerAuthReason): Promise<boolean> {
  const current = authPrompt.value
  // 已经在等解锁时又收到「需要登录」，升级为登录；反之保持登录。
  if (!current || (current.reason === 'locked' && reason === 'required')) authPrompt.value = { reason }
  return new Promise((resolve) => waiters.push(resolve))
}

export function settleOfficerAuth(ok: boolean) {
  authPrompt.value = null
  for (const resolve of waiters.splice(0)) resolve(ok)
}

export interface SessionProbe {
  configured: boolean
  required?: boolean
  authenticated: boolean
  locked: boolean
}

/** 根据会话探测结果判断还需不需要验证；未配置民警名录时不拦截。 */
export function authReasonForSession(session: SessionProbe): OfficerAuthReason | null {
  if (!(session.required ?? session.configured)) return null
  if (!session.authenticated) return 'required'
  if (session.locked) return 'locked'
  return null
}
