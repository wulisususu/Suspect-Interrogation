import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import type { CaseSummary, FactItem } from '../types/interrogation'
import type { SelfQuestion } from '../utils/selfService'
import SelfServiceAnswerPage from './SelfServiceAnswerPage.vue'
import SelfServiceIdentityPage from './SelfServiceIdentityPage.vue'
import workspaceSource from '../views/SelfServiceWorkspace.vue?raw'

const summary = {
  id: '2026-0428', suspectName: '王某某', gender: '女', nation: '汉', birthDate: '1992-05-14', idNumber: '330502199205142319',
  address: '湖州市吴兴区凤凰路××号', identitySource: 'OCR', officerName: '张伟', state: 'READY', stage: 'IDENTITY',
} as unknown as CaseSummary
const render = async (component: object, props: Record<string, unknown>) =>
  (await renderToString(createSSRApp(component, props))).replace(/<!--[\s\S]*?-->/g, '')

const facts: FactItem[] = [
  { key: 'contact', label: '联系方式', value: '13812346721', status: 'confirmed' },
  { key: 'current_address', label: '现住址', value: '湖州市吴兴区织里镇××路××号', status: 'confirmed' },
]

describe('SelfServiceIdentityPage', () => {
  it('greets the person, shows masked identity details and keeps 开始回答 locked until confirmed', async () => {
    const props = { summary, facts, officerName: '张伟', caseType: '盗窃（电动车）', confirmed: false, busy: false }
    const html = await render(SelfServiceIdentityPage, props)
    expect(html).toContain('您好，王某某')
    expect(html).toContain('最后由民警张伟确认后形成笔录')
    expect(html).toContain('1992 年 5 月 14 日')
    expect(html).toContain('3305**********2319')
    expect(html).not.toContain('330502199205142319')
    expect(html).toContain('138****6721')
    expect(html).toContain('以上信息无误')
    expect(html).toContain('信息有误或读取失败，请找民警手工补填')
    expect(html).toContain('盗窃（电动车）')
    expect(html).toContain('开始之前，请知悉')
    expect(html).toContain('全程录音默认开启')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>开始回答/)
    const ready = await render(SelfServiceIdentityPage, { ...props, confirmed: true })
    expect(ready).not.toMatch(/<button[^>]*disabled[^>]*>开始回答/)
  })
})

describe('SelfServiceAnswerPage', () => {
  const questions: SelfQuestion[] = [
    { id: 'q1', text: '什么时候发现车不见的', elementKey: 'time_place', elementLabel: '案发时间与地点', elementOrdinal: 1, answer: '7 时 20 分', formal: false },
    { id: 'q2', text: '车是什么牌子、什么颜色', elementKey: 'vehicle', elementLabel: '车辆特征', elementOrdinal: 2, answer: '雅迪 深蓝', formal: false },
    { id: 'q3', text: '你当时锁车了吗？', elementKey: 'lock', elementLabel: '锁具情况', elementOrdinal: 3, answer: '', formal: false },
    { id: 'q4', text: '最后一次看到车是什么时候', elementKey: 'last_seen', elementLabel: '最后见到时间', elementOrdinal: 4, answer: '', formal: false },
  ]
  const base = {
    questions, current: 2, recording: true, busy: false, liveText: '我那天是锁了的，就锁在单元门口那个柱子上', elapsedMs: 26_000,
    confirmedIds: ['q1'], officerLabel: '民警张伟（038291）', templateTitle: '盗窃（电动车）', blockedReason: '',
  }

  it('shows the recording state of the current question with its element and live transcript', async () => {
    const html = await render(SelfServiceAnswerPage, base)
    expect(html).toContain('第 3 题 / 共 4 题')
    expect(html).toContain('《盗窃（电动车）》模板 · 核心要素 4 项')
    expect(html).toContain('核心要素 ③ 锁具情况')
    expect(html).toContain('你当时锁车了吗？')
    expect(html).toContain('正在录音')
    expect(html).toContain('00:26')
    expect(html).toContain('说完了 · 结束录音')
    expect(html).toContain('重新说一遍')
    expect(html).toContain('已经记下 2 题')
    expect(html).toContain('民警张伟（038291） 全程在场')
    expect(html).toContain('我说的没错，本题确认无误')
    expect(html).toContain('答：我那天是锁了的')
    expect(html).toContain('未答的 2 题将标记为「未获取」')
    expect(html).toContain('结束并交民警定稿')
  })

  it('asks the person to check an unconfirmed transcript and offers to redo it', async () => {
    const html = await render(SelfServiceAnswerPage, { ...base, recording: false, current: 1 })
    expect(html).toContain('我们听到的是「雅迪 深蓝」，对吗？')
    expect(html).toContain('不对，改一下')
    expect(html).toContain('下一题')
    const confirmed = await render(SelfServiceAnswerPage, { ...base, recording: false, current: 0 })
    expect(confirmed).not.toContain('我们听到的是')
  })

  it('starts unanswered questions with 开始回答 and blocks recording with a reason when devices are not ready', async () => {
    const html = await render(SelfServiceAnswerPage, { ...base, recording: false, liveText: '', blockedReason: '暂时不能录音：待完成 设备自检，请找在场民警处理' })
    expect(html).toMatch(/<button[^>]*disabled[^>]*>.*开始回答/s)
    expect(html).toContain('暂时不能录音')
    expect(html).toContain('答：（未获取）')
  })
})

describe('SelfServiceWorkspace', () => {
  it('keeps answers as drafts and leaves self-service only through the officer handover', () => {
    expect(workspaceSource).toContain("{ draft: true, replace: target.replace }")
    expect(workspaceSource).toContain("recordSelfServiceEvent(props.caseId, 'HANDOVER')")
    expect(workspaceSource).toContain("recordSelfServiceEvent(props.caseId, 'IDENTITY_CONFIRM')")
    expect(workspaceSource).toContain(':steps="SELF_SERVICE_STEPS"')
    expect(workspaceSource).not.toContain("emit('back')")
    // 卸载钩子晚于人工模式工作台挂载执行，交回后不能再清空同一案件的上下文
    expect(workspaceSource).toContain('if (handedOver) return')
  })
})
