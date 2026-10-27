/** 长按确认：按住满 durationMs 才触发，中途松开即取消（定稿冻结等不可撤销操作用）。 */
export function createLongPress(durationMs: number, onConfirm: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let startedAt = 0

  function cancel() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
    startedAt = 0
  }

  function start() {
    cancel()
    startedAt = Date.now()
    timer = setTimeout(() => {
      timer = undefined
      startedAt = 0
      onConfirm()
    }, durationMs)
  }

  function progress() {
    return startedAt ? Math.min(1, (Date.now() - startedAt) / durationMs) : 0
  }

  return { start, cancel, progress }
}
