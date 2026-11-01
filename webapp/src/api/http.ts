import axios from 'axios'
import { authReasonForError, authReasonForSession, autoPromptEnabled, requestOfficerAuth } from '../auth/officerAuth'
import { audioInputMode } from '../config/audioInput'
import { runtimeConfig } from '../config/runtime'

export const AUDIO_INPUT_REQUEST_HEADER = 'X-Suspect-Audio-Input'

export function currentAudioInputRequestHeaders(): Record<string, string> {
  return { [AUDIO_INPUT_REQUEST_HEADER]: audioInputMode }
}

export const http = axios.create({
  baseURL: runtimeConfig.apiBaseUrl,
  withCredentials: true,
  timeout: 30_000,
})

http.interceptors.request.use((config) => {
  config.headers[AUDIO_INPUT_REQUEST_HEADER] = audioInputMode
  return config
})

// 会话过期或面板被锁：叠加验证弹窗而不是让每个页面各自报错。错误照常抛给调用方，
// 调用方在验证通过后由用户重试，或由自带重试的通道（音频续传、实时事件）自动恢复。
http.interceptors.response.use(undefined, (error) => {
  const status: number | undefined = error?.response?.status
  const code: string | undefined = error?.response?.data?.code
  // 登录 / 解锁接口自身的失败由验证弹窗处理，不再递归弹窗。
  const url: string = error?.config?.url ?? ''
  const reason = url.includes('/api/v1/auth/') ? null : authReasonForError(status, code)
  if (reason && autoPromptEnabled.value) void requestOfficerAuth(reason)
  return Promise.reject(error)
})

let lastProbeAt = 0

/**
 * WebSocket 握手被鉴权拒绝时浏览器只给出 1006，看不到原因；
 * 重连失败时调用它探测一次会话（最多每 10 秒一次），需要时弹出验证。
 */
export async function probeOfficerAuth(): Promise<void> {
  const now = Date.now()
  if (now - lastProbeAt < 10_000) return
  lastProbeAt = now
  try {
    const response = await http.get('/api/v1/auth/session')
    const session = response.data?.data ?? response.data
    const reason = session ? authReasonForSession(session) : null
    if (reason && autoPromptEnabled.value) void requestOfficerAuth(reason)
  } catch {
    // 后端不可达时由原有的离线提示负责
  }
}
