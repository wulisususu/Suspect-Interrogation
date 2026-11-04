import { fetchAuthSession, type AuthSession } from '../api/officers'

/**
 * 办理入口的登录门槛：人工模式与自助模式都要民警先验证身份。
 * 登录一次当天有效（后端会话 24 小时），期间再点任一模式直接进入；
 * 尚未配置民警名录、且后端不强制认证的预览环境照旧放行。
 */
export function sessionAllowsEntry(session: AuthSession): boolean {
  if (session.authenticated) return !session.locked
  return !session.configured && !session.required
}

export async function officerSessionActive(): Promise<boolean> {
  try {
    return sessionAllowsEntry(await fetchAuthSession())
  } catch {
    // 探测失败交给登录页处理（登录页自己会再探测一次并给出提示）
    return false
  }
}
