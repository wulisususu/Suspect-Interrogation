<script setup lang="ts">
import { computed } from 'vue'
import type { CaseSummary } from '../types/interrogation'
import { ledgerStatus } from '../utils/caseLedger'
import { unfinishedCases } from '../utils/kioskLobby'
import { formatRecordTime } from '../utils/recordPaper'
import EmptyState from './EmptyState.vue'

/** 未完成办理（样板 P23）：断电 / 崩溃后的续做、中途离开的挂起会话从这里恢复；草稿不计入。 */
const props = defineProps<{ cases: CaseSummary[] }>()
const emit = defineEmits<{ open: [caseId: string]; detail: [caseId: string] }>()

const pending = computed(() => unfinishedCases(props.cases).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)))
</script>

<template>
  <section class="pending-list">
    <header>
      <h1>未完成办理 · 共 {{ pending.length }} 项</h1>
      <p>断电 / 崩溃后的续做、当事人中途离开的挂起会话都从这里恢复；仅「草稿」不计入本列表</p>
    </header>
    <EmptyState v-if="!pending.length" kind="empty" title="暂无未完成办理" description="所有已开始的笔录都已归档" />
    <ul v-else>
      <li v-for="item in pending" :key="item.id">
        <div class="pending-main">
          <strong>案 {{ item.id }}</strong>
          <span>{{ item.suspectName || '未填写' }} · 主审 {{ item.officerName || '—' }}</span>
        </div>
        <span class="pending-status">{{ ledgerStatus(item) }}</span>
        <span class="pending-time">最后更新 {{ formatRecordTime(item.updatedAt) }}</span>
        <div class="pending-actions">
          <button type="button" class="pending-secondary" @click="emit('detail', item.id)">详情</button>
          <button type="button" class="pending-primary" @click="emit('open', item.id)">继续办理</button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.pending-list { display: flex; flex-direction: column; gap: var(--space-4); max-width: 1400px; margin: 0 auto; }
.pending-list header h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.pending-list header p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.pending-list ul { display: flex; flex-direction: column; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.pending-list li { display: grid; grid-template-columns: minmax(0, 2fr) 120px 220px auto; align-items: center; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.pending-main { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.pending-main strong { color: var(--ink-900); font-size: var(--text-base); }
.pending-main span, .pending-time { color: var(--ink-500); font-size: var(--text-xs); }
.pending-status { justify-self: start; padding: 3px var(--space-2); border-radius: var(--radius-pill); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-xs); }
.pending-actions { display: flex; gap: var(--space-2); }
.pending-primary, .pending-secondary { min-height: 40px; padding: 0 var(--space-4); border-radius: var(--radius-sm); font-size: var(--text-sm); font-weight: 600; }
.pending-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.pending-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
</style>
