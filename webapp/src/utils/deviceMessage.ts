/**
 * 设备异常的业务提示（走查 D37）：后端 / SDK 给的英文技术原因不直接展示给民警，
 * 换成中文说明与恢复办法，原文作为技术详情保留。
 */
export interface DeviceMessage {
  text: string
  detail: string
}

const HAS_CHINESE = /[一-龥]/

export function readerMessage(reason?: string | null): DeviceMessage {
  const raw = (reason ?? '').trim()
  if (raw && HAS_CHINESE.test(raw)) return { text: raw, detail: '' }
  return {
    text: '身份证读卡器未配置或未连接，可点「人工录入」继续建案',
    detail: raw,
  }
}
