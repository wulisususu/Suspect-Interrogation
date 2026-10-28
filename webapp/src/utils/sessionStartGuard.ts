import type { RuntimeCapabilities } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'

export interface SessionStartGuard {
  identityRecorded: boolean
  deviceReady: boolean
  missing: string[]
  disabled: boolean
  reason: string
}

/** 开始正式询问的前置条件：身份已录入、麦克风与语音识别就绪。声纹已移出办理流程。 */
export function sessionStartGuard(summary: CaseSummary, capabilities: RuntimeCapabilities | null): SessionStartGuard {
  const identityRecorded = Boolean(summary.suspectName && summary.suspectName !== '待录入' && summary.idNumber && summary.identitySource)
  const deviceReady = capabilities?.microphone.state === 'AVAILABLE' && capabilities?.asr.state === 'AVAILABLE'
  const missing = [!identityRecorded && '身份信息', !deviceReady && '设备自检'].filter((value): value is string => Boolean(value))
  return {
    identityRecorded,
    deviceReady,
    missing,
    disabled: missing.length > 0,
    reason: missing.length ? '完成以下项目后解锁：' + missing.join('、') : '身份与设备已就绪，可以开始询问',
  }
}
