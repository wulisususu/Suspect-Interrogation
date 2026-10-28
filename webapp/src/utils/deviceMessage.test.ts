import { describe, expect, it } from 'vitest'
import { readerMessage } from './deviceMessage'

describe('readerMessage', () => {
  it('replaces raw SDK errors with a Chinese explanation and keeps the original as detail', () => {
    expect(readerMessage('identity reader SDK library was not found')).toEqual({
      text: '身份证读卡器未配置或未连接，可点「人工录入」继续建案',
      detail: 'identity reader SDK library was not found',
    })
  })

  it('keeps messages that are already readable', () => {
    expect(readerMessage('读卡失败，请重新放置身份证')).toEqual({ text: '读卡失败，请重新放置身份证', detail: '' })
    expect(readerMessage('')).toEqual({ text: '身份证读卡器未配置或未连接，可点「人工录入」继续建案', detail: '' })
  })
})
