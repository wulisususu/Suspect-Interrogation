import { computed } from 'vue'
import { useInterrogationStore } from '../stores/interrogation'
import { useTemplateInterrogationStore } from '../stores/templateInterrogation'
import type { SessionStartGuard } from '../utils/sessionStartGuard'

/**
 * 逐题录音的公共部分：人工模式的「点卡即录」与自助模式的「本人作答」共用。
 * 负责按需开始询问、开一次录音、停止后取回这一次录音的全部最终片段。
 * 片段如何挂到题目上（待摘入 / 追加一问）由调用方决定。
 */
export function useAnswerCapture(guard: () => SessionStartGuard) {
  const store = useInterrogationStore()
  const templateStore = useTemplateInterrogationStore()

  /** 本次录音已识别的文字（最终片段 + 正在识别的半句），用于实时上屏。 */
  const liveText = computed(() => {
    const captureId = store.capture.captureSessionId
    if (!store.capture.running || !captureId) return ''
    const finals = templateStore.dialogueHistory
      .filter((item) => item.captureSessionId === captureId && !['DISCARDED', 'SUPERSEDED'].includes(item.state))
      .map((item) => (item.editedText || item.rawText).trim())
    return [...finals, store.capture.partialText?.trim() || ''].filter(Boolean).join('')
  })

  async function ensureSessionRunning(): Promise<boolean> {
    if (store.session.status === 'RUNNING') return true
    if (store.session.status !== 'READY') {
      store.feedback(store.session.status === 'PAUSED' ? '询问已暂停，请先继续询问' : '本次询问已结束，不能继续录音', true)
      return false
    }
    const current = guard()
    if (current.disabled) {
      store.feedback(current.reason, true)
      return false
    }
    await store.startSession()
    // startSession 会替换 session；TS 仍按进入时的 READY 收窄，这里重新读取。
    const started: string = store.session.status
    return started === 'RUNNING'
  }

  async function beginCapture(): Promise<string | null> {
    if (store.capture.running || store.captureBusy) return null
    if (!(await ensureSessionRunning())) return null
    await store.startCapture()
    return store.capture.running ? store.capture.captureSessionId || null : null
  }

  /** 停止录音并取回这一次录音的全部最终片段。
   * 收尾片段在采集线程退出时才提交，实测比停止响应晚约一秒；立即读取会扑空，
   * 把已识别成功的答案误报成"没有听清"。片段缺席时轮询补读。 */
  async function finishCapture(captureId: string) {
    if (!(await store.stopCapture(undefined, false))) return null
    const caseId = store.caseId
    if (!caseId) return null
    await templateStore.initialize(caseId)
    const collect = () => templateStore.dialogueHistory
      .filter((item) => item.captureSessionId === captureId && !['DISCARDED', 'SUPERSEDED'].includes(item.state) && (item.editedText || item.rawText).trim())
      .sort((a, b) => a.startedAtMs - b.startedAtMs || a.ordinal - b.ordinal)
    let fragments = collect()
    const deadline = Date.now() + 8000
    let emptyReads = 0
    while (!fragments.length && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await templateStore.loadDialogueHistory()
      fragments = collect()
      if (fragments.length) break
      // 停止响应已确认 ASR 完成、连续两轮仍无片段：这次确实没说出内容，提前收场。
      emptyReads = store.capture.asrStatus === 'COMPLETE' ? emptyReads + 1 : 0
      if (emptyReads >= 2) break
    }
    return fragments
  }

  return { liveText, ensureSessionRunning, beginCapture, finishCapture }
}
