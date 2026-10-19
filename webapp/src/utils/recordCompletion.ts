import type { TemporaryAsrFragment } from '../types/interrogation'

export function fragmentNeedsReview(item: TemporaryAsrFragment) {
  return item.lowConfidence || item.speaker === 'UNKNOWN' || item.speaker === 'OFFICER_FALLBACK' || item.speakerSource === 'PENDING_ANALYSIS'
}

export function orderedReviewFragments(items: TemporaryAsrFragment[], uncertainFirst: boolean) {
  return items.filter(item => item.state !== 'DISCARDED' && item.state !== 'SUPERSEDED')
    .sort((a, b) => (uncertainFirst ? Number(fragmentNeedsReview(b)) - Number(fragmentNeedsReview(a)) : 0)
      || a.startedAtMs - b.startedAtMs || a.ordinal - b.ordinal || a.id.localeCompare(b.id))
}

export function canConfirmFragment(item: TemporaryAsrFragment) {
  return ['PENDING', 'EDITED'].includes(item.state) && item.speaker !== 'UNKNOWN'
    && item.speakerSource !== 'PENDING_ANALYSIS' && Boolean((item.editedText || item.rawText).trim())
}

export function confirmationCandidates(items: TemporaryAsrFragment[]) {
  return items.filter(item => canConfirmFragment(item) && !fragmentNeedsReview(item)
    && item.confidenceSource !== 'UNAVAILABLE' && item.confidence != null && item.confidence >= .96)
}

export function freezeBlockReason(value: {
  sessionStatus: string; captureRunning: boolean; busy: boolean; loading: boolean; loadError: string
  frozen: boolean; checks: boolean[]; unresolvedFragments: number; unresolvedQa: number
  recordError?: string; hasQuestions?: boolean
  asrStatus?: string | null; speakerStatus?: string | null; recordingStatus?: string | null
}) {
  if (value.frozen) return '笔录已冻结，不能重复冻结'
  if (value.loading || value.loadError) return '签署状态尚未读取成功，请重试'
  if (value.recordError) return '正式笔录尚未读取成功，请返回复核重试'
  if (value.hasQuestions === false) return '正式笔录暂无问答内容，请返回复核检查'
  if (value.busy) return '正在保存或处理，请稍候'
  if (value.captureRunning) return '请先停止录音'
  if (value.sessionStatus !== 'COMPLETED') return '请先结束审讯，再复核并冻结笔录'
  if (value.recordingStatus === 'INCOMPLETE' || value.recordingStatus === 'CAPTURING') return '录音尚未完整归档，请先处理'
  if (value.asrStatus && value.asrStatus !== 'COMPLETE') return '文字转写尚未完成，请先处理'
  if (value.speakerStatus && !['COMPLETE', 'NEEDS_REVIEW'].includes(value.speakerStatus)) return '说话人分析尚未完成，请先处理'
  if (value.unresolvedFragments) return `还有 ${value.unresolvedFragments} 条转写片段待确认或丢弃`
  if (value.unresolvedQa) return `还有 ${value.unresolvedQa} 组问答待处置`
  if (value.checks.length !== 5 || value.checks.some(checked => !checked)) return '请逐项完成打印前核对'
  return ''
}
