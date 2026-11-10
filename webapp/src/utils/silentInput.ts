/**
 * 录音开始后检测"麦克风到底有没有收到声音"。
 *
 * 以前的失败表现是：录完只提示"没有识别到语音"，民警无从判断是识别坏了、
 * 网络断了，还是麦克风选错/被静音。
 *
 * 判据用 RMS 而不是峰值：底噪的瞬时尖峰也能到几千（实测一段纯噪声峰值 9100），
 * 用峰值会把"完全没采到人声"误判成"有声音"，提示永远不出现。按 0.5 秒窗口实测，
 * 正常说话 RMS 在 1000 以上，而设备底噪稳定在 260–630，所以取 700 作分界。
 */
export const SILENT_INPUT_RMS = 700
export const SILENT_INPUT_WINDOW_MS = 3000

export interface SilentInputState {
  /** 第一次采样时间；0 表示尚未开始计时。 */
  startedAt: number
  /** 已经给出结论（要么听到声音，要么已告警），后续不再重复判断。 */
  settled: boolean
}

export function initialSilentInputState(): SilentInputState {
  return { startedAt: 0, settled: false }
}

export function nextSilentInputState(
  state: SilentInputState,
  level: { rms: number; peak: number },
  now: number,
): SilentInputState & { warn: boolean } {
  if (state.settled) return { ...state, warn: false }
  if (level.rms >= SILENT_INPUT_RMS) return { startedAt: state.startedAt, settled: true, warn: false }
  const startedAt = state.startedAt || now
  if (now - startedAt < SILENT_INPUT_WINDOW_MS) return { startedAt, settled: false, warn: false }
  return { startedAt, settled: true, warn: true }
}

export function silentInputMessage(deviceLabel?: string): string {
  const device = deviceLabel ? `（当前输入：${deviceLabel}）` : ''
  return `麦克风没有收到声音${device}；请检查系统输入设备、蓝牙耳机是否选错或被静音`
}
