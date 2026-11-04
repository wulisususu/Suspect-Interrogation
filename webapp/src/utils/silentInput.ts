/**
 * 录音开始后检测"麦克风到底有没有收到声音"。
 *
 * 以前的失败表现是：录完只提示"没有识别到语音"，民警无从判断是识别坏了、
 * 网络断了，还是麦克风选错/被静音。实测底噪峰值约 300、正常说话在 1500 以上，
 * 所以用 900 作为分界，开始录音 3 秒内一直没有超过它就直接报"麦克风没有收到声音"。
 */
export const SILENT_INPUT_PEAK = 900
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
  peak: number,
  now: number,
): SilentInputState & { warn: boolean } {
  if (state.settled) return { ...state, warn: false }
  if (peak >= SILENT_INPUT_PEAK) return { startedAt: state.startedAt, settled: true, warn: false }
  const startedAt = state.startedAt || now
  if (now - startedAt < SILENT_INPUT_WINDOW_MS) return { startedAt, settled: false, warn: false }
  return { startedAt, settled: true, warn: true }
}

export function silentInputMessage(deviceLabel?: string): string {
  const device = deviceLabel ? `（当前输入：${deviceLabel}）` : ''
  return `麦克风没有收到声音${device}；请检查系统输入设备、蓝牙耳机是否选错或被静音`
}
