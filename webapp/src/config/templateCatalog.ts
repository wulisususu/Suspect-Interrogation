/**
 * 笔录模板目录（样板 P05）
 *
 * 后端尚无模板目录接口：每个案件只带出一个真实模板（backendKey 对应 template-workspace
 * 的 templateKey）。其余条目是按设计稿整理的示例模板，结构与将来的接口返回一致，
 * 接入「模板管理」后由民警在前端维护，这里整体替换为接口数据即可。
 */

export type TemplateCategory = 'theft' | 'injury' | 'traffic' | 'other'
export type TemplateTone = 'primary' | 'danger' | 'warning' | 'neutral'

export interface TemplateBadge {
  label: string
  tone: 'danger' | 'success' | 'warning'
}

export interface TemplateCatalogItem {
  id: string
  title: string
  category: TemplateCategory
  /** 卡片左上角分类标签 */
  tag: string
  tagTone: TemplateTone
  badge?: TemplateBadge
  /** 卡片右上角学习状态，如「已学习 5 份」 */
  learning: string
  summary: string
  elements: string[]
  minutes: number
  scene: string
  presetQuestions: string[]
  /** 对应后端真实模板；没有即为示例模板 */
  backendKey?: string
}

export const TEMPLATE_CATEGORIES: { key: TemplateCategory; label: string }[] = [
  { key: 'theft', label: '盗窃类' },
  { key: 'injury', label: '伤害类' },
  { key: 'traffic', label: '交通类' },
  { key: 'other', label: '其他' },
]

export const TEMPLATE_CATALOG: TemplateCatalogItem[] = [
  {
    id: 'theft-ebike',
    title: '盗窃（电动车）',
    category: 'theft',
    tag: '盗窃',
    tagTone: 'primary',
    badge: { label: '推荐', tone: 'danger' },
    learning: '已学习 5 份',
    summary: '案发时间地点、车辆特征、锁具情况、最后见到时间、可疑对象、车辆价值',
    elements: ['案发时间与地点', '车辆品牌 / 颜色 / 购买时间', '锁具情况（遥控锁 / U 型锁）', '最后见到车辆的时间', '可疑对象与目击情况', '车辆价值与发票凭证'],
    minutes: 15,
    scene: '报案大厅 / 被害人',
    presetQuestions: ['请讲一下事情经过？', '车辆什么品牌、颜色？', '当时锁了吗？', '你最后一次看到车是什么时候？', '有没有看到可疑人员？', '车辆购置价值大约多少？'],
  },
  {
    id: 'theft-vehicle-goods',
    title: '盗窃（车内财物）',
    category: 'theft',
    tag: '盗窃',
    tagTone: 'primary',
    learning: '已学习 4 份',
    summary: '停车位置、车门锁闭情况、财物清单与价值、发现经过、监控覆盖情况',
    elements: ['停车时间与位置', '车辆信息', '车门锁闭情况', '被盗财物清单', '财物价值', '发现经过', '监控覆盖情况'],
    minutes: 18,
    scene: '报案大厅 / 被害人',
    presetQuestions: ['车停在什么位置？', '下车时车门锁好了吗？', '车内少了哪些东西？', '这些东西大约值多少钱？', '什么时候发现被盗的？', '附近有没有监控？'],
  },
  {
    id: 'injury-assault',
    title: '故意伤害（殴打他人）',
    category: 'injury',
    tag: '伤害',
    tagTone: 'danger',
    learning: '已学习 6 份',
    summary: '起因经过、伤情与就医、致伤工具、在场证人、双方关系、调解意愿',
    elements: ['案发时间与地点', '事情起因', '经过', '伤情与就医', '致伤工具', '在场证人', '双方关系', '调解意愿'],
    minutes: 25,
    scene: '被害人 / 证人',
    presetQuestions: ['请讲一下事情经过？', '双方因为什么起的冲突？', '对方用什么打的你？', '你哪里受了伤，去医院了吗？', '当时有谁在场？', '你们之前认识吗？', '是否愿意调解？'],
  },
  {
    id: 'traffic-simple',
    title: '交通事故（简易处理）',
    category: 'traffic',
    tag: '交通',
    tagTone: 'warning',
    badge: { label: '最快', tone: 'success' },
    learning: '已学习 3 份',
    summary: '事故时间地点、双方车辆、责任认定、损失情况、保险信息',
    elements: ['事故时间与地点', '双方车辆信息', '事故经过与责任', '损失情况', '保险信息'],
    minutes: 10,
    scene: '交警简易处理',
    presetQuestions: ['事故在什么时间、什么地点发生？', '双方各是什么车？', '事故是怎么发生的？', '车辆和人员损失情况如何？', '双方投保了哪家保险？'],
  },
  {
    id: 'report-general',
    title: '报案登记（通用）',
    category: 'other',
    tag: '通用',
    tagTone: 'neutral',
    learning: '未学习 · 基础模板',
    summary: '报案人身份、案由、事情经过、诉求与联系方式，任何案由均可起步',
    elements: ['报案人身份', '案由', '事情经过', '诉求与联系方式'],
    minutes: 8,
    scene: '任何场景',
    presetQuestions: ['你要报什么案？', '请讲一下事情经过？', '你希望公安机关怎么处理？', '怎么联系到你？'],
  },
  {
    id: 'suspect-inquiry',
    title: '嫌疑人询问',
    category: 'other',
    tag: '其他',
    tagTone: 'neutral',
    badge: { label: '自助式不适用', tone: 'warning' },
    learning: '仅人工模式',
    summary: '讯问策略引导、认罪认罚、退赃退赔、前科劣迹、同案关系、作案工具去向',
    elements: ['时间', '地点', '动机 / 目的', '手段 / 工具', '行为经过', '证据对应', '事后处置 / 后果', '前科劣迹', '同案关系'],
    minutes: 40,
    scene: '办案区 / 嫌疑人',
    presetQuestions: [],
    backendKey: 'SUSPECT_INQUIRY_V1',
  },
]

/** 生成后的正本骨架（样板 P05 右栏），要素数随模板变化。 */
export function recordSkeleton(elementCount: number): string[] {
  return [
    '公文头：机关名 + 询问笔录 + 编号',
    '权利义务告知段（法定条款自动带入）',
    '被询问人信息 14 字段（身份证读取回填）',
    `问答正文区 · 按 ${elementCount} 项要素顺序排`,
    '结尾声明 + 签字位 3 处',
  ]
}
