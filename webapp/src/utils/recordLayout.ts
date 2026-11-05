import type { CaseSummary, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'

/**
 * 询问笔录纸面排版：仿派出所打印件（A4、宋体四号、每行 10 mm 横线、页脚「第N页，共M页」）。
 *
 * 版心按扫描样件实测：左右边距 21 mm、上边距 22 mm、每页 22 行、行距 10 mm；
 * 首页前 3 行为「第 N 次」与标题「询问笔录」，其后为抬头栏目，空一行起排问答。
 * 断行由这里完成（而不是交给浏览器自动换行），这样每一行都落在横线上，分页与页码可以精确算出。
 */
export const RECORD_PAGE = {
  widthMm: 210,
  heightMm: 297,
  marginXMm: 21,
  topMm: 22,
  pitchMm: 10,
  rows: 22,
  /** 首页标题区占用的行数 */
  titleRows: 3,
  bodyPt: 14,
} as const

const PX_PER_MM = 96 / 25.4
export const RECORD_FONT_PX = (RECORD_PAGE.bodyPt * 96) / 72
/** 版心宽度（CSS px）。留 1% 余量：测量与实际渲染的细微差别不能把一行挤成两行。 */
export const RECORD_LINE_PX = (RECORD_PAGE.widthMm - 2 * RECORD_PAGE.marginXMm) * PX_PER_MM * 0.99
export const RECORD_PAGE_PX = RECORD_PAGE.widthMm * PX_PER_MM

/** 按正文字号测量一段文字的宽度（px）。 */
export type MeasureText = (text: string) => number

/** 无法测量时（服务端渲染、测试）的估算：汉字与全角符号一个字宽，其余半个字宽（与宋体一致）。 */
export function estimateTextWidth(text: string): number {
  let ems = 0
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0
    const full = code >= 0x2e80 || (code >= 0x2010 && code <= 0x206f && '—…“”‘’'.includes(char))
    ems += full ? 1 : 0.5
  }
  return ems * RECORD_FONT_PX
}

/** 不能出现在行首的标点（避头）。 */
const NO_LINE_START = new Set('，。、；：？！）》」』】〕〉”’…—·％%,.;:?!)]}'.split(''))
/** 不能出现在行尾的标点（避尾）。 */
const NO_LINE_END = new Set('（《「『【〔〈“‘([{'.split(''))

/** 拆成排版单元：连续的字母数字（证件号、车牌、金额）不拆开，其余逐字。 */
function tokenize(text: string): string[] {
  return text.match(/[A-Za-z0-9]+(?:[.\-:/][A-Za-z0-9]+)*|[\s\S]/gu) ?? []
}

/**
 * 断行：首行可用宽度 `firstWidth`，续行 `restWidth`。
 * 避头尾：行首遇到避头标点时把上一字一并带下去；行尾不留左括号、左引号。
 */
export function breakLines(text: string, measure: MeasureText, firstWidth: number, restWidth = firstWidth): string[] {
  const lines: string[] = []
  const cache = new Map<string, number>()
  const widthOf = (token: string) => {
    let width = cache.get(token)
    if (width === undefined) cache.set(token, (width = measure(token)))
    return width
  }
  let current: string[] = []
  let used = 0
  const limit = () => (lines.length ? restWidth : firstWidth)
  const flush = () => { lines.push(current.join('')); current = []; used = 0 }

  const queue = tokenize(text)
  for (let index = 0; index < queue.length; index += 1) {
    const token = queue[index]!
    const width = widthOf(token)
    if (used + width <= limit()) { current.push(token); used += width; continue }
    if (!current.length) {
      // 单个单元比整行还宽（超长的连续字母数字）：逐字硬断。
      if (token.length > 1) { queue.splice(index, 1, ...token.split('')); index -= 1; continue }
      current.push(token); flush(); continue
    }
    const carry: string[] = []
    if (NO_LINE_START.has(token[0]!) && current.length > 1) carry.unshift(current.pop()!)
    while (current.length > 1 && NO_LINE_END.has(current[current.length - 1]!)) carry.unshift(current.pop()!)
    flush()
    current = carry
    used = carry.reduce((sum, item) => sum + widthOf(item), 0)
    index -= 1
  }
  if (current.length || !lines.length) flush()
  return lines
}

/** 抬头栏目里的一段：标签 + 下划线填写区。`em` 为固定宽度（字），缺省则占满本行余下宽度。 */
export interface RecordField {
  label: string
  value: string
  em?: number
  /** 与前一段之间额外留白（字） */
  gapEm?: number
}

export type RecordRow =
  | { kind: 'fields'; fields: RecordField[] }
  /** 抬头栏目内容过长时的续行：整行下划线 */
  | { kind: 'fill'; text: string }
  | { kind: 'blank' }
  /** 问答正文的一行；`justify` 为段落中间行（两端对齐） */
  | { kind: 'line'; text: string; justify: boolean }

export interface RecordPageLayout {
  number: number
  first: boolean
  rows: RecordRow[]
  /** 文末签章区从本页第几行开始；本页不放签章区为 null */
  footerAtRow: number | null
}

export interface RecordHeader {
  round: string
  rows: RecordRow[]
}

function pad(value: number) { return String(value).padStart(2, '0') }
/** 样件格式：2026年 8月 19日 15时 20分 */
export function recordClock(ms?: number | null): string {
  if (!ms) return ''
  const d = new Date(ms)
  return `${d.getFullYear()}年 ${d.getMonth() + 1}月 ${d.getDate()}日 ${d.getHours()}时 ${pad(d.getMinutes())}分`
}
export function recordDate(value?: string | null): string {
  const match = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(value || '')
  return match ? `${match[1]}年${Number(match[2])}月${Number(match[3])}日` : (value || '')
}

const PLACEHOLDERS = new Set(['未录入', '未填写', '待录入', '当前警官'])
const clean = (value?: string | null) => {
  const text = (value ?? '').trim()
  return text && !PLACEHOLDERS.has(text) ? text : ''
}

/**
 * 抬头栏目。空值留空白下划线（与纸质件一致，由民警手填），不写「未填写」。
 * `unitFallback` 为部署配置的单位名，本案未填写工作单位时使用。
 */
export function recordHeader(summary: CaseSummary, facts: FactItem[], session: SessionState, unitFallback = '', officerName = ''): RecordHeader {
  const fact = (key: string) => clean(facts.find((item) => item.key === key)?.value)
  const unit = fact('officer_unit') || clean(unitFallback)
  const start = recordClock(session.startedAt || summary.createdAt)
  const idType = fact('id_document_type') || '身份证'
  const idNumber = clean(summary.idNumber)
  return {
    round: fact('interrogation_round'),
    rows: [
      { kind: 'fields', fields: [{ label: '时间', value: start, em: 13 }, { label: '至', value: recordClock(session.endedAt), gapEm: 0.5 }] },
      { kind: 'fields', fields: [{ label: '地点', value: fact('interrogation_place') }] },
      { kind: 'fields', fields: [{ label: '询问人', value: clean(officerName), em: 4.5 }, { label: '工作单位', value: unit, gapEm: 0.5 }] },
      { kind: 'fields', fields: [{ label: '记录人', value: fact('recorder_name'), em: 4.5 }, { label: '工作单位', value: fact('recorder_unit') || unit, gapEm: 0.5 }] },
      { kind: 'fields', fields: [{ label: '被询问人', value: clean(summary.suspectName) }] },
      { kind: 'fields', fields: [{ label: '身份证件种类及号码', value: idNumber ? `${idType}，${idNumber}` : idType + '，' }] },
      { kind: 'fields', fields: [
        { label: '性别', value: clean(summary.gender), em: 4 },
        { label: '出生日期', value: recordDate(summary.birthDate), em: 9, gapEm: 0.5 },
        { label: '人大代表', value: fact('peoples_representative'), em: 3, gapEm: 2 },
      ] },
      { kind: 'fields', fields: [{ label: '联系方式', value: fact('contact') }] },
      { kind: 'fields', fields: [{ label: '现住址', value: fact('current_address') }] },
      { kind: 'fields', fields: [{ label: '户籍所在地', value: fact('household_registration') }] },
    ],
  }
}

const LABEL_GAP_EM = 0.5

/** 抬头栏目最后一段占满余宽；内容过长时拆出续行（整行下划线）。 */
export function wrapFieldRows(rows: RecordRow[], measure: MeasureText, lineWidth = RECORD_LINE_PX): RecordRow[] {
  const em = RECORD_FONT_PX
  return rows.flatMap((row): RecordRow[] => {
    if (row.kind !== 'fields') return [row]
    const last = row.fields[row.fields.length - 1]!
    if (last.em !== undefined || !last.value) return [row]
    const before = row.fields.slice(0, -1).reduce((sum, field) => sum + measure(field.label) + ((field.gapEm ?? 0) + LABEL_GAP_EM + (field.em ?? 0)) * em, 0)
    const available = lineWidth - before - measure(last.label) - ((last.gapEm ?? 0) + LABEL_GAP_EM) * em
    const [first, ...rest] = breakLines(last.value, measure, Math.max(available, em * 2), lineWidth)
    return [
      { kind: 'fields', fields: [...row.fields.slice(0, -1), { ...last, value: first ?? '' }] },
      ...rest.map((text): RecordRow => ({ kind: 'fill', text })),
    ]
  })
}

/** 两端对齐的下限：一行排到九成以上才拉齐，长串数字（证件号）整体折到下一行时，上一行保持左对齐，不被拉出大空隙。 */
const JUSTIFY_MIN_FILL = 0.9

/** 正文问答 → 行。答案里的换行另起一行；未作答显示 `emptyAnswer`。 */
export function qaRows(questions: Pick<FormalQuestion, 'text' | 'formalAnswerText'>[], measure: MeasureText, emptyAnswer = '', lineWidth = RECORD_LINE_PX): RecordRow[] {
  const paragraph = (prefix: string, text: string): RecordRow[] => text.split(/\r?\n/).flatMap((part, index) => {
    const lines = breakLines((index === 0 ? prefix : '') + part.trimEnd(), measure, lineWidth)
    return lines.map((line, at): RecordRow => ({ kind: 'line', text: line, justify: at < lines.length - 1 && measure(line) >= lineWidth * JUSTIFY_MIN_FILL }))
  })
  return questions.flatMap((question) => [
    ...paragraph('问：', question.text?.trim() ?? ''),
    ...paragraph('答：', question.formalAnswerText?.trim() || emptyAnswer),
  ])
}

/**
 * 分页：首页标题占 3 行，抬头栏目紧随其后并空一行，问答顺排；每页 22 行。
 * `footerRows` 为文末签章区所需行数，末页剩余行不够时另起一页。
 */
export function paginateRecord(header: RecordRow[], body: RecordRow[], footerRows = 0): RecordPageLayout[] {
  const pages: RecordPageLayout[] = [{ number: 1, first: true, rows: [], footerAtRow: null }]
  const capacity = (page: RecordPageLayout) => RECORD_PAGE.rows - (page.first ? RECORD_PAGE.titleRows : 0)
  const place = (row: RecordRow) => {
    let page = pages[pages.length - 1]!
    if (page.rows.length >= capacity(page)) pages.push((page = { number: pages.length + 1, first: false, rows: [], footerAtRow: null }))
    page.rows.push(row)
  }
  for (const row of header) place(row)
  if (header.length) place({ kind: 'blank' })
  for (const row of body) place(row)
  if (footerRows > 0) {
    let last = pages[pages.length - 1]!
    if (capacity(last) - last.rows.length < footerRows) pages.push((last = { number: pages.length + 1, first: false, rows: [], footerAtRow: null }))
    last.footerAtRow = last.rows.length
  }
  return pages
}
