<script setup lang="ts">
import { computed } from 'vue'
import type { CaseSummary, FactItem, SessionState } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { branding } from '../config/branding'
import { factValue, formatRecordTime } from '../utils/recordPaper'

/**
 * 询问笔录纸面
 *
 * 签署页、归档页与打印件共用同一份纸面：抬头、身份信息、问答正文一致，
 * 文末内容（签章热区或签名行）由使用方通过 footer 插槽给出。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  /** 标题下的一行说明；默认显示询问次数 */
  subtitle?: string
}>()

const ordered = computed(() => [...props.questions].sort((a, b) => a.sortOrder - b.sortOrder))
const fact = (key: string, fallback?: string) => factValue(props.facts, key, fallback)
</script>

<template>
  <article class="record-paper">
    <header><h2>询 问 笔 录</h2><p>{{ subtitle ?? `询问次数：${fact('interrogation_round')}` }}</p></header>
    <section class="record-paper-meta">
      <p>询问时间：{{ formatRecordTime(session.startedAt || summary.createdAt) }} 至 {{ formatRecordTime(session.endedAt) }}</p>
      <p>询问地点：{{ fact('interrogation_place') }}</p>
      <p>询问人：{{ summary.officerName || '未填写' }}　工作单位：{{ fact('officer_unit', branding.unitName || undefined) }}</p>
      <p>记录人：{{ fact('recorder_name') }}　工作单位：{{ fact('recorder_unit', fact('officer_unit', branding.unitName || undefined)) }}</p>
      <p>被询问人：{{ summary.suspectName || '未填写' }}　性别：{{ summary.gender || '未填写' }}　出生日期：{{ summary.birthDate || '未填写' }}</p>
      <p>证件类型：{{ fact('id_document_type', '身份证') }}　证件号码：{{ summary.idNumber || '未填写' }}</p>
      <p>联系方式：{{ fact('contact') }}　现住址：{{ fact('current_address') }}</p>
      <p>案件编号：{{ summary.id }}</p>
    </section>
    <section class="record-paper-body">
      <div v-for="question in ordered" :key="question.id" class="record-paper-qa">
        <p><b>问：</b>{{ question.text }}</p>
        <p><b>答：</b>{{ question.formalAnswerText || '（未获取）' }}</p>
      </div>
      <p v-if="!ordered.length" class="record-paper-empty">暂无正式问答内容，请返回定稿校验检查笔录。</p>
    </section>
    <slot name="footer" />
  </article>
</template>

<style scoped>
.record-paper { box-sizing: border-box; padding: 52px 48px 38px; background: var(--paper-bg); color: var(--paper-ink); font: var(--text-lg)/1.85 var(--font-serif); }
.record-paper > header { text-align: center; margin-bottom: 26px; }
.record-paper h2 { margin: 0; font-size: var(--text-3xl); font-weight: 600; letter-spacing: 4px; }
.record-paper header p { margin: 4px 0; color: var(--paper-muted); font-size: var(--text-base); }
.record-paper p { overflow-wrap: anywhere; }
.record-paper-meta { padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px solid var(--paper-rule); }
.record-paper-meta p { margin: 0 0 6px; }
.record-paper-qa p { margin: 0 0 12px; white-space: pre-wrap; }
.record-paper-qa b { font-weight: 600; }
.record-paper-empty { color: var(--paper-muted); }
@media print { .record-paper { zoom: 1 !important; width: auto !important; min-height: 0 !important; padding: 0; } }
</style>
