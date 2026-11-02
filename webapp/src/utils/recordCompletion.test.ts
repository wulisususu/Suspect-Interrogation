import { describe, expect, it } from 'vitest'
import { canConfirmFragment, confirmationCandidates, fragmentNeedsReview, freezeBlockReason, orderedReviewFragments } from './recordCompletion'
import type { TemporaryAsrFragment } from '../types/interrogation'

const fragment = (id: string, values: Partial<TemporaryAsrFragment> = {}) => ({
  id, ordinal: 1, startedAtMs: 0, editedText: '测试转写', rawText: '测试转写', speaker: 'SUSPECT',
  state: 'PENDING', confidence: .98, confidenceSource: 'FUNASR', lowConfidence: false,
  speakerSource: 'SPEAKER_EMBEDDING', ...values,
}) as TemporaryAsrFragment

describe('record completion safety and review ordering', () => {
  it('prioritizes uncertain active fragments without changing the source collection', () => {
    const items = [fragment('good'), fragment('low', { lowConfidence: true, startedAtMs: 500 }), fragment('old', { state: 'SUPERSEDED' }), fragment('discarded', { state: 'DISCARDED' })]
    expect(orderedReviewFragments(items, true).map(item => item.id)).toEqual(['low', 'good'])
    expect(orderedReviewFragments(items, false).map(item => item.id)).toEqual(['good', 'low'])
    expect(items.map(item => item.id)).toEqual(['good', 'low', 'old', 'discarded'])
  })

  it('only offers high-confidence batch selection for eligible, unconfirmed fragments', () => {
    const items = [fragment('good'), fragment('unknown', { speaker: 'UNKNOWN' }), fragment('unavailable', { confidenceSource: 'UNAVAILABLE' }), fragment('low', { lowConfidence: true }), fragment('confirmed', { state: 'CONFIRMED' }), fragment('empty', { rawText: '', editedText: '' })]
    // 说话人判定永久下线后 UNKNOWN 不再是排除理由，只剩置信度与状态筛选。
    expect(confirmationCandidates(items).map(item => item.id)).toEqual(['good', 'unknown'])
  })

  it('lets a fragment with no speaker decision be confirmed instead of only discarded', () => {
    const retired = fragment('retired', { speaker: 'UNKNOWN', speakerSource: 'PENDING_ANALYSIS' })
    expect(fragmentNeedsReview(retired)).toBe(false)
    expect(canConfirmFragment(retired)).toBe(true)
    expect(canConfirmFragment({ ...retired, state: 'CONFIRMED' })).toBe(false)
    expect(canConfirmFragment({ ...retired, rawText: '', editedText: '' })).toBe(false)
    // 置信度低仍然要人工核对
    expect(fragmentNeedsReview({ ...retired, lowConfidence: true })).toBe(true)
  })

  const ready = { sessionStatus: 'COMPLETED', captureRunning: false, busy: false, loading: false, loadError: '', recordError: '', hasQuestions: true, frozen: false, asrStatus: 'COMPLETE', speakerStatus: 'COMPLETE', recordingStatus: 'COMPLETE' }
  it('requires stopped, processed audio before freezing but no manual acknowledgement', () => {
    expect(freezeBlockReason(ready)).toBe('')
    // 定稿会由后端结束仍在进行的询问，进行中 / 暂停的会话可以直接确认定稿。
    expect(freezeBlockReason({ ...ready, sessionStatus: 'RUNNING' })).toBe('')
    expect(freezeBlockReason({ ...ready, sessionStatus: 'PAUSED' })).toBe('')
    expect(freezeBlockReason({ ...ready, captureRunning: true })).toContain('录音')
    expect(freezeBlockReason({ ...ready, asrStatus: 'FINALIZING' })).toContain('转写')
    expect(freezeBlockReason({ ...ready, recordingStatus: 'INCOMPLETE' })).toContain('归档')
  })

  it('blocks unresolved or failed state, including missing server state', () => {
    expect(freezeBlockReason({ ...ready, loadError: '网络异常' })).toContain('状态')
    expect(freezeBlockReason({ ...ready, sessionStatus: 'READY' })).toContain('尚未开始询问')
    expect(freezeBlockReason({ ...ready, frozen: true })).toContain('冻结')
    expect(freezeBlockReason({ ...ready, busy: true })).toContain('保存')
    expect(freezeBlockReason({ ...ready, recordError: '读取失败' })).toContain('笔录')
    expect(freezeBlockReason({ ...ready, hasQuestions: false })).toContain('笔录')
  })

  it('does not block on a speaker status the retired voiceprint stage will never advance', () => {
    // 声纹下线后 SPEAKER 任务不再调度，采集的 speaker_status 长期停在 PENDING；
    // 后端冻结也不校验它，所以 PENDING/NEEDS_REVIEW 都不能挡住定稿。
    expect(freezeBlockReason({ ...ready, speakerStatus: 'PENDING' })).toBe('')
    expect(freezeBlockReason({ ...ready, speakerStatus: 'NEEDS_REVIEW' })).toBe('')
    expect(freezeBlockReason({ ...ready, speakerStatus: null })).toBe('')
    // 真正在分析时才提示等待。
    expect(freezeBlockReason({ ...ready, speakerStatus: 'PROCESSING' })).toContain('说话人分析')
    expect(freezeBlockReason({ ...ready, speakerStatus: 'RUNNING' })).toContain('说话人分析')
  })
})
