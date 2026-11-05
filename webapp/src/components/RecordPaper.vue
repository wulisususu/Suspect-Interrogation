<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, useSlots } from 'vue'
import type { CaseSummary, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { branding } from '../config/branding'
import { officerDisplayName } from '../utils/officer'
import {
  RECORD_FONT_PX, RECORD_PAGE, RECORD_PAGE_PX, estimateTextWidth, paginateRecord, qaRows, recordHeader, wrapFieldRows,
  type MeasureText, type RecordPageLayout,
} from '../utils/recordLayout'

/**
 * 询问笔录纸面（仿派出所打印件）
 *
 * A4 逐页排版：宋体四号、每行 10 mm 横线、首页「第 N 次」与标题「询问笔录」、抬头栏目下划线填写、
 * 问答顺排、页脚「第N页，共M页」。定稿校验预览、签署页、打印件与归档件共用这一份纸面，所见即所印。
 * 文末签章区由使用方通过 footer 插槽给出，占用 `footerRows` 行，末页放不下时另起一页。
 */
const props = withDefaults(defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  /** 屏幕显示比例；不传则按容器宽度自适应（最大 100%）。打印时恒为 100%。 */
  scale?: number
  /** 文末签章区占用的行数（每行 10 mm），仅在提供 footer 插槽时生效 */
  footerRows?: number
  /** 未作答的题在「答：」后显示的文字 */
  emptyAnswer?: string
}>(), { scale: undefined, footerRows: 5, emptyAnswer: '（未获取）' })

const slots = useSlots()
const root = ref<HTMLElement | null>(null)
const measure = shallowRef<MeasureText>(estimateTextWidth)
const fitScale = ref(1)
let observer: ResizeObserver | null = null

const ordered = computed(() => [...props.questions].filter((item) => item.active !== false).sort((a, b) => a.sortOrder - b.sortOrder))
const header = computed(() => recordHeader(props.summary, props.facts, props.session, branding.unitName || '', officerDisplayName(props.summary.officerName)))
const pages = computed<RecordPageLayout[]>(() => paginateRecord(
  wrapFieldRows(header.value.rows, measure.value),
  qaRows(ordered.value, measure.value, props.emptyAnswer),
  slots.footer ? props.footerRows : 0,
))
const zoom = computed(() => props.scale ?? fitScale.value)

const mm = (value: number) => `${value}mm`
function footerStyle(page: RecordPageLayout) {
  const startRow = (page.first ? RECORD_PAGE.titleRows : 0) + (page.footerAtRow ?? 0)
  return { top: mm(RECORD_PAGE.topMm + startRow * RECORD_PAGE.pitchMm), height: mm((RECORD_PAGE.rows - startRow) * RECORD_PAGE.pitchMm) }
}

/** 用纸面实际字体测宽：与浏览器渲染一致，断行才不会溢出横线。 */
function useCanvasMeasure(element: HTMLElement) {
  const context = document.createElement('canvas').getContext('2d')
  if (!context) return
  context.font = `${RECORD_FONT_PX}px ${getComputedStyle(element).fontFamily}`
  measure.value = (text: string) => context.measureText(text).width
}

onMounted(() => {
  const element = root.value
  if (!element) return
  useCanvasMeasure(element)
  // 随前端分发的宋体是按需下载的：下载完成后按真实字形重新测宽断行。
  const fonts = document.fonts
  if (fonts) {
    Promise.all([fonts.load(`${RECORD_FONT_PX}px ${getComputedStyle(element).fontFamily}`, '问答'), fonts.ready])
      .then(() => { if (root.value) useCanvasMeasure(root.value) })
      .catch(() => undefined)
  }
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => { fitScale.value = Math.min(1, element.clientWidth / RECORD_PAGE_PX) || 1 })
    observer.observe(element)
  }
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <article ref="root" class="record-paper" aria-label="询问笔录">
    <div class="record-sheets" :style="{ zoom }">
      <section v-for="page in pages" :key="page.number" class="record-sheet" :aria-label="`第${page.number}页，共${pages.length}页`">
        <header v-if="page.first" class="record-sheet-title">
          <p class="record-round">第<span>{{ header.round }}</span>次</p>
          <h2>询问笔录</h2>
        </header>
        <div class="record-rows">
          <div v-for="(row, index) in page.rows" :key="index" class="record-row" :class="[`is-${row.kind}`, { 'is-justify': row.kind === 'line' && row.justify }]">
            <template v-if="row.kind === 'fields'">
              <template v-for="(field, at) in row.fields" :key="at">
                <span class="record-label" :style="field.gapEm ? { marginLeft: `${field.gapEm}em` } : undefined">{{ field.label }}</span>
                <span class="record-value" :class="{ 'is-grow': field.em === undefined }" :style="field.em !== undefined ? { width: `${field.em}em` } : undefined">{{ field.value }}</span>
              </template>
            </template>
            <span v-else-if="row.kind === 'fill'" class="record-value is-grow">{{ row.text }}</span>
            <template v-else-if="row.kind === 'line'">{{ row.text }}</template>
          </div>
        </div>
        <div v-if="page.footerAtRow !== null" class="record-sheet-footer" :style="footerStyle(page)"><slot name="footer" /></div>
        <p class="record-page-no">第{{ page.number }}页，共{{ pages.length }}页</p>
      </section>
    </div>
  </article>
</template>

<style scoped>
.record-paper { width: 100%; min-width: 0; font-family: var(--font-record); }
.record-sheets { display: flex; flex-direction: column; align-items: center; gap: 18px; }
.record-sheet {
  position: relative; box-sizing: border-box; flex: none;
  width: 210mm; height: 297mm; padding: 22mm 21mm 0;
  background: var(--paper-bg); color: var(--record-ink);
  box-shadow: 0 0 0 1px var(--paper-rule), 0 2px 10px rgba(0, 0, 0, 0.12);
  font-size: 14pt; line-height: 1;
}
.record-sheet-title { position: relative; height: 30mm; }
.record-round { position: absolute; top: 4mm; right: 0; display: flex; gap: 1em; margin: 0; }
.record-round span { min-width: 1em; text-align: center; }
.record-sheet-title h2 { position: absolute; top: 13mm; left: 0; right: 0; margin: 0; text-align: center; font-size: 24pt; font-weight: 400; letter-spacing: 0.04em; }
.record-row { box-sizing: border-box; height: 10mm; white-space: nowrap; overflow: hidden; }
.record-row.is-fields, .record-row.is-fill { display: flex; align-items: flex-end; padding-bottom: 0.6mm; }
.record-row.is-line { padding-top: 4.1mm; border-bottom: 1px solid var(--record-rule); }
.record-row.is-justify { text-align: justify; text-align-last: justify; }
.record-label { flex: none; box-sizing: border-box; min-height: 1.35em; border-bottom: 1px solid transparent; }
.record-value { flex: none; box-sizing: border-box; min-height: 1.35em; margin-left: 0.5em; padding: 0 0.25em; border-bottom: 1px solid var(--record-rule); overflow: hidden; }
.record-value.is-grow { flex: 1; min-width: 0; }
.record-row.is-fill .record-value { margin-left: 0; padding-left: 0; }
.record-sheet-footer { position: absolute; left: 21mm; right: 21mm; overflow: hidden; }
.record-page-no { position: absolute; left: 0; right: 0; bottom: 26mm; margin: 0; text-align: center; font-size: 14pt; }

@media print {
  .record-sheets { zoom: 1 !important; display: block; }
  .record-sheet { box-shadow: none; break-after: page; page-break-after: always; }
  .record-sheet:last-child { break-after: auto; page-break-after: auto; }
}
</style>

<style>
/* 随前端分发的宋体（Noto Serif CJK SC 的 GB2312 子集，SIL OFL 1.1，见 assets/fonts/OFL.txt） */
@font-face {
  font-family: "RecordSong";
  src: url("../assets/fonts/record-song.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: block;
}

/*
 * 纸面自带 A4 版心，打印时页面不再另加页边距，浏览器也就不会印出网址与日期页眉页脚。
 * 界面的最小宽度（body min-width）在打印时取消，否则浏览器会把整页缩小去适配纸宽，纸面不再是 1:1。
 */
@media print {
  @page { size: A4; margin: 0; }
  html, body, #app { min-width: 0 !important; height: auto !important; overflow: visible !important; }
}
</style>
