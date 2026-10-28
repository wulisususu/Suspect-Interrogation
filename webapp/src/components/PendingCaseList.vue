<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import type { CaseSummary } from '../types/interrogation'
import { casePhase, ledgerStatus } from '../utils/caseLedger'
import { unfinishedCases } from '../utils/kioskLobby'
import { formatRecordTime } from '../utils/recordPaper'
import EmptyState from './EmptyState.vue'

/**
 * 未完成办理（样板 P20）：表格按中断事由 / 案件 / 时间 / 当前状态 / 操作横向比较，分页浏览。
 * 后端尚未记录中断原因与停留题号（见 docs/backend-todo.md），如实显示「未记录」，不用更新时间冒充中断时间。
 */
const props = defineProps<{ cases: CaseSummary[] }>()
const emit = defineEmits<{ open: [caseId: string]; detail: [caseId: string] }>()

const pageSize = 10
const page = ref(1)
const pending = computed(() => unfinishedCases(props.cases).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)))
const pages = computed(() => Math.max(1, Math.ceil(pending.value.length / pageSize)))
const visible = computed(() => pending.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch(pages, (total) => { if (page.value > total) page.value = total })

const caseTypeLabel = (value?: string) => (value === 'suspect_interrogation' ? '嫌疑人询问' : value || '未填写')
</script>

<template>
  <section class="pending-list">
    <header>
      <h1>未完成办理 · 共 {{ pending.length }} 项</h1>
      <p>断电 / 崩溃后的续做、当事人中途离开的挂起会话都从这里恢复；仅「草稿」不计入本列表</p>
    </header>
    <EmptyState v-if="!pending.length" kind="empty" title="暂无未完成办理" description="所有已开始的笔录都已归档" />
    <div v-else class="pending-table-shell">
      <table class="pending-table">
        <thead>
          <tr><th>中断事由</th><th>案件</th><th>最后更新时间</th><th>当前状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in visible" :key="item.id">
            <td class="pending-reason">未记录</td>
            <td><strong>案 {{ item.id }}</strong><span> · {{ caseTypeLabel(item.caseType) }} · {{ item.suspectName || '未填写' }}</span></td>
            <td class="pending-time">{{ formatRecordTime(item.updatedAt) }}</td>
            <td><span class="case-status" :class="`is-${casePhase(item).toLowerCase()}`">{{ ledgerStatus(item) }}</span></td>
            <td>
              <div class="pending-actions">
                <button type="button" class="pending-link" @click="emit('open', item.id)">继续办理</button>
                <i aria-hidden="true">·</i>
                <button type="button" class="pending-link is-muted" @click="emit('detail', item.id)">详情</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <footer class="pending-footer">
        <span>从这里回到该案件的办理页面，已落库内容不丢；中断原因与停留题号待后端接入</span>
        <nav v-if="pages > 1" class="pending-pager" aria-label="分页">
          <button type="button" :disabled="page <= 1" @click="page -= 1"><ChevronLeft :size="16" aria-hidden="true" />上一页</button>
          <span>{{ page }} / {{ pages }}</span>
          <button type="button" :disabled="page >= pages" @click="page += 1">下一页<ChevronRight :size="16" aria-hidden="true" /></button>
        </nav>
      </footer>
    </div>
  </section>
</template>

<style scoped>
.pending-list { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.pending-list header h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.pending-list header p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.pending-table-shell { display: flex; flex-direction: column; border-radius: var(--radius-lg); background: var(--surface); overflow: hidden; }
.pending-table { width: 100%; border-collapse: collapse; text-align: left; font-size: var(--text-base); }
.pending-table th { padding: var(--space-3) var(--space-5); background: var(--primary-50); color: var(--ink-500); font-size: var(--text-sm); font-weight: 600; white-space: nowrap; }
.pending-table td { height: 64px; padding: 0 var(--space-5); border-bottom: 1px solid var(--line-100); color: var(--ink-700); white-space: nowrap; }
.pending-table td strong { color: var(--ink-900); font-weight: 600; }
.pending-table td span { color: var(--ink-500); }
.pending-table td.pending-reason { color: var(--ink-400); }
.pending-time { color: var(--ink-500); font-variant-numeric: tabular-nums; }
.pending-actions { display: flex; align-items: center; gap: var(--space-2); }
.pending-actions i { color: var(--ink-300); font-style: normal; }
.pending-link { min-height: 40px; padding: 0 var(--space-1); border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-base); font-weight: 600; }
.pending-link.is-muted { color: var(--ink-500); font-weight: 400; }
.pending-footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-3) var(--space-5); color: var(--ink-400); font-size: var(--text-sm); }
.pending-pager { display: flex; align-items: center; gap: var(--space-3); }
.pending-pager button { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 40px; padding: 0 var(--space-3); border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-sm); }
.pending-pager button:disabled { color: var(--ink-300); }
</style>
