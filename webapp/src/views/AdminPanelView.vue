<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Archive, AudioLines, BookOpen, ChevronRight, PenLine } from '@lucide/vue'
import { fetchCases } from '../api/interrogation'
import { fetchExperience, fetchKnowledgeEntries } from '../api/knowledge'
import { fetchOfficers } from '../api/officers'
import type { CaseSummary } from '../types/interrogation'
import type { AdminPanel } from '../utils/rootRoute'
import { unfinishedCases } from '../utils/kioskLobby'

/**
 * 管理面板（样板 P19）：四个管理入口 + 其他后台页面的快捷入口。
 * 整张卡片都可点击进入；卡片里的统计取真实数据，读取失败显示「—」不阻断进入。
 */
const emit = defineEmits<{
  cases: []
  pending: []
  audit: []
  placeholder: [panel: AdminPanel]
}>()

const cases = ref<CaseSummary[]>([])
const loadFailed = ref(false)
const knowledge = ref<{ total: number; verified: number; pending: number } | null>(null)
const officerCount = ref<number | null>(null)

onMounted(async () => {
  void fetchOfficers(true).then((list) => { officerCount.value = list.length }).catch(() => undefined)
  void Promise.all([fetchKnowledgeEntries({}), fetchExperience('PENDING').catch(() => null)]).then(([list, experience]) => {
    knowledge.value = {
      total: list.length,
      verified: list.filter((item) => item.status === 'verified').length,
      pending: experience?.counts.PENDING ?? 0,
    }
  }).catch(() => undefined)
  try { cases.value = await fetchCases(200) } catch { loadFailed.value = true }
})

const knowledgeStats = computed(() => knowledge.value
  ? [['知识条目', `${knowledge.value.total} 条`], ['已验证', `${knowledge.value.verified} 条`], ['经验待审', `${knowledge.value.pending} 条`]]
  : [['知识条目', '—'], ['已验证', '—'], ['经验待审', '—']])

const caseStats = computed(() => {
  const start = new Date()
  start.setDate(1)
  start.setHours(0, 0, 0, 0)
  const latest = [...cases.value].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0]
  return [
    ['本月案件', loadFailed.value ? '读取失败' : `${cases.value.filter((item) => (item.createdAt || 0) >= start.getTime()).length} 起`],
    ['最近办理', latest ? `案 ${latest.id}` : '—'],
    ['未完成', `${unfinishedCases(cases.value).length} 项`],
  ]
})

const entries = computed(() => [
  { key: 'cases', title: '案件记录', desc: '全部案件查询与归档 · 导出 Word/PDF、打印', icon: Archive, tone: 'primary', tags: ['案件查询', '归档管理', '导出与打印'], stats: caseStats.value, open: () => emit('cases') },
  { key: 'knowledge', title: '知识库管理', desc: '问话知识条目增删改查 · 纯后台管理', icon: BookOpen, tone: 'success', tags: ['条目增删改', '版本留痕', '热词同步'], stats: knowledgeStats.value, open: () => emit('placeholder', 'knowledge') },
  { key: 'signatures', title: '民警签名管理', desc: '民警签名预先录入 · 管理与调用', icon: PenLine, tone: 'warning', tags: ['签名预录入', '管理与调用', '调用记录留痕'], stats: [['民警名录', officerCount.value === null ? '—' : `${officerCount.value} 人`], ['签名调用', '签署时调用 · 留痕']], open: () => emit('placeholder', 'signatures') },
  { key: 'recordings', title: '录音查看', desc: '双通道录音 · 分段转写与全程原始文件', icon: AudioLines, tone: 'primary', tags: ['双通道录音', '分段转写', '全程原始文件'], stats: [['查看方式', '按案件 · 两路录音'], ['原始文件', '全程录音随卷保存']], open: () => emit('placeholder', 'recordings') },
])
</script>

<template>
  <section class="admin-panel">
    <header class="admin-panel-head">
      <div>
        <h1>管理功能</h1>
        <p>点击卡片进入 · 全部管理操作记入操作日志（操作人 / 时间 / 内容）</p>
      </div>
      <nav class="admin-quick" aria-label="其他后台页面">
        <button type="button" @click="emit('pending')">未完成办理 ›</button>
        <button type="button" @click="emit('placeholder', 'templates')">模板管理 ›</button>
        <button type="button" @click="emit('audit')">操作日志 ›</button>
      </nav>
    </header>

    <div class="admin-entries">
      <article v-for="entry in entries" :key="entry.key" class="admin-entry" :class="`is-${entry.tone}`">
        <header>
          <span class="admin-entry-icon" :class="`is-${entry.tone}`" aria-hidden="true"><component :is="entry.icon" :size="30" /></span>
          <div>
            <h2>{{ entry.title }}</h2>
            <p>{{ entry.desc }}</p>
          </div>
          <!-- 按钮的点击区铺满整张卡片（见 .admin-entry-open::after） -->
          <button type="button" class="admin-entry-open" :aria-label="`进入${entry.title}`" @click="entry.open">进入<ChevronRight :size="20" aria-hidden="true" /></button>
        </header>
        <ul class="admin-entry-tags"><li v-for="tag in entry.tags" :key="tag">{{ tag }}</li></ul>
        <dl>
          <div v-for="[label, value] in entry.stats" :key="label"><dt>{{ label }}</dt><dd :class="{ 'is-text': value.length > 6 }">{{ value }}</dd></div>
        </dl>
      </article>
    </div>

    <p class="admin-policy">安全策略：后台须民警登录（当天有效），验证后 10 分钟内免验，锁定由民警手动触发，全部管理操作记入日志</p>
  </section>
</template>

<style scoped>
.admin-panel { display: flex; flex-direction: column; gap: var(--space-5); width: 100%; min-height: 100%; }
.admin-panel-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.admin-panel-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 650; }
.admin-panel-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.admin-quick { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.admin-quick button { min-height: 44px; padding: 0 var(--space-4); border: 0; border-radius: var(--radius-pill); background: var(--primary-100); color: var(--primary-600); font-size: var(--text-sm); font-weight: 600; cursor: pointer; }
.admin-entries { display: grid; flex: 1 1 auto; grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-rows: minmax(0, 1fr); gap: var(--space-5); }
.admin-entry { position: relative; display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-6) var(--space-8); border: 2px solid transparent; border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s; }
.admin-entry:hover { border-color: var(--primary-500); box-shadow: var(--shadow-pop); }
.admin-entry:active { transform: scale(0.995); }
.admin-entry:focus-within { border-color: var(--primary-600); }
.admin-entry > header { display: flex; align-items: center; gap: var(--space-4); }
.admin-entry h2 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 650; }
.admin-entry header p { margin: var(--space-2) 0 0; color: var(--ink-500); font-size: var(--text-md); }
.admin-entry-icon { display: grid; place-items: center; width: 64px; height: 64px; flex: none; border-radius: var(--radius-md); background: var(--primary-100); color: var(--primary-600); }
.admin-entry-icon.is-success { background: var(--success-100); color: var(--success-700); }
.admin-entry-icon.is-warning { background: var(--warning-100); color: var(--warning-700); }
.admin-entry-open { display: inline-flex; align-items: center; gap: var(--space-1); flex: none; min-height: 48px; margin-left: auto; padding: 0 var(--space-3) 0 var(--space-5); border: 0; border-radius: var(--radius-pill); background: var(--primary-50); color: var(--primary-700); font-size: var(--text-md); font-weight: 600; cursor: pointer; }
.admin-entry-open::after { content: ''; position: absolute; inset: 0; border-radius: inherit; }
.admin-entry-open:focus-visible { outline: none; }
.admin-entry:hover .admin-entry-open { background: var(--primary-600); color: var(--surface); }
.admin-entry-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.admin-entry-tags li { padding: var(--space-2) var(--space-4); border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-700); font-size: var(--text-sm); }
.admin-entry dl { display: grid; flex: 1 1 auto; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-3); margin: 0; }
.admin-entry dl div { display: flex; flex-direction: column; justify-content: center; gap: var(--space-2); min-height: 112px; padding: var(--space-4) var(--space-5); border-radius: var(--radius-md); background: var(--surface-sunken); }
.admin-entry dt { color: var(--ink-500); font-size: var(--text-sm); }
.admin-entry dd { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 650; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.admin-entry dd.is-text { font-size: var(--text-lg); font-weight: 600; }
.admin-policy { margin: 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-sm); }
@media (max-width: 1100px) { .admin-entries { grid-template-columns: 1fr; grid-auto-rows: auto; } }
</style>
