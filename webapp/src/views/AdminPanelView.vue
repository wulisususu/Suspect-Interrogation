<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Archive, AudioLines, BookOpen, ChevronRight, PenLine } from '@lucide/vue'
import { fetchCases } from '../api/interrogation'
import type { CaseSummary } from '../types/interrogation'
import type { AdminPanel } from '../utils/rootRoute'
import { unfinishedCases } from '../utils/kioskLobby'

/**
 * 管理面板（样板 P19）：四个管理入口 + 其他后台页面的快捷入口。
 * 案件记录的统计取真实案件数据；尚无后端能力的入口在卡片中注明「功能待接入」。
 */
const emit = defineEmits<{
  cases: []
  pending: []
  audit: []
  placeholder: [panel: AdminPanel]
}>()

const cases = ref<CaseSummary[]>([])
const loadFailed = ref(false)

onMounted(async () => {
  try { cases.value = await fetchCases(200) } catch { loadFailed.value = true }
})

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
  { key: 'knowledge', title: '知识库管理', desc: '问话知识条目增删改查 · 纯后台管理', icon: BookOpen, tone: 'success', tags: ['条目增删改', '版本留痕', '热词同步'], stats: [['状态', '可导入 Vault']], open: () => emit('placeholder', 'knowledge') },
  { key: 'signatures', title: '民警签名管理', desc: '民警签名预先录入 · 管理与调用', icon: PenLine, tone: 'warning', tags: ['签名预录入', '管理与调用', '调用记录留痕'], stats: [['状态', '需民警验证']], open: () => emit('placeholder', 'signatures') },
  { key: 'recordings', title: '录音查看', desc: '双通道录音 · 分段转写与全程原始文件', icon: AudioLines, tone: 'primary', tags: ['双通道录音', '分段转写', '全程原始文件'], stats: [['状态', '需民警验证']], open: () => emit('placeholder', 'recordings') },
])
</script>

<template>
  <section class="admin-panel">
    <header class="admin-panel-head">
      <div>
        <h1>管理功能</h1>
        <p>四项管理入口 · 管理操作接入认证后记入操作日志（操作人 / 时间 / 内容）</p>
      </div>
      <nav class="admin-quick" aria-label="其他后台页面">
        <button type="button" @click="emit('pending')">未完成办理 ›</button>
        <button type="button" @click="emit('placeholder', 'templates')">模板管理 ›</button>
        <button type="button" @click="emit('audit')">操作日志 ›</button>
      </nav>
    </header>

    <div class="admin-entries">
      <article v-for="entry in entries" :key="entry.key" class="admin-entry">
        <header>
          <span class="admin-entry-icon" :class="`is-${entry.tone}`" aria-hidden="true"><component :is="entry.icon" :size="22" /></span>
          <div>
            <h2>{{ entry.title }}</h2>
            <p>{{ entry.desc }}</p>
          </div>
          <button type="button" class="admin-entry-open" :aria-label="`进入${entry.title}`" @click="entry.open"><ChevronRight :size="16" /></button>
        </header>
        <ul class="admin-entry-tags"><li v-for="tag in entry.tags" :key="tag">{{ tag }}</li></ul>
        <dl>
          <div v-for="[label, value] in entry.stats" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
        </dl>
      </article>
    </div>

    <p class="admin-policy">安全策略：民警认证尚未接入，当前后台为界面预览；接入后验证 10 分钟内免验，锁定由民警手动触发，全部管理操作记入日志</p>
  </section>
</template>

<style scoped>
.admin-panel { display: flex; flex-direction: column; gap: var(--space-5); width: 100%; }
.admin-panel-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.admin-panel-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.admin-panel-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.admin-quick { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.admin-quick button { min-height: 36px; padding: 0 var(--space-3); border: 0; border-radius: var(--radius-pill); background: var(--primary-100); color: var(--primary-600); font-size: var(--text-xs); font-weight: 600; }
.admin-entries { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.admin-entry { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.admin-entry > header { display: flex; align-items: center; gap: var(--space-3); }
.admin-entry h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); font-weight: 600; }
.admin-entry header p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.admin-entry-icon { display: grid; place-items: center; width: 48px; height: 48px; flex: none; border-radius: var(--radius-md); background: var(--primary-100); color: var(--primary-600); }
.admin-entry-icon.is-success { background: var(--success-100); color: var(--success-700); }
.admin-entry-icon.is-warning { background: var(--warning-100); color: var(--warning-700); }
.admin-entry-open { display: grid; place-items: center; width: 36px; height: 36px; margin-left: auto; border: 1px solid var(--line-300); border-radius: 50%; background: var(--surface); color: var(--ink-500); }
.admin-entry-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding: 0 0 var(--space-3); border-bottom: 1px solid var(--line-200); list-style: none; }
.admin-entry-tags li { padding: var(--space-1) var(--space-3); border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-xs); }
.admin-entry dl { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; font-size: var(--text-sm); }
.admin-entry dl div { display: flex; gap: var(--space-3); }
.admin-entry dt { color: var(--ink-500); }
.admin-entry dd { margin: 0; color: var(--ink-700); }
.admin-policy { margin: 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-xs); }
@media (max-width: 1100px) { .admin-entries { grid-template-columns: 1fr; } }
</style>
