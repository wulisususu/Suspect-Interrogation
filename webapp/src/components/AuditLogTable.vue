<script setup lang="ts">
import { auditActionLabel, auditActorLabel, auditTargetLabel, type AuditEntry } from '../api/audit'
import { formatRecordTime } from '../utils/recordPaper'
import EmptyState from './EmptyState.vue'

/** 操作日志表（样板 P29）：只读留置，不提供删除。 */
defineProps<{ entries: AuditEntry[]; caseSelected: boolean }>()
</script>

<template>
  <div class="audit-table">
    <p class="audit-note">只读留置，不可删除 · 随案归档并与文书内容互相溯源</p>
    <EmptyState v-if="!caseSelected" kind="empty" title="请选择案件查看操作日志" description="在上方选择一个案件" />
    <EmptyState v-else-if="!entries.length" kind="empty" title="该案件暂无操作记录" />
    <table v-else>
      <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th></tr></thead>
      <tbody>
        <tr v-for="entry in entries" :key="entry.id">
          <td>{{ formatRecordTime(entry.createdAt) }}</td>
          <td :class="{ 'is-system': !entry.actorId.trim() }">{{ auditActorLabel(entry.actorId) }}</td>
          <td :title="entry.action">{{ auditActionLabel(entry.action) }}</td>
          <td :title="`${entry.targetType} · ${entry.targetId}`">{{ auditTargetLabel(entry) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.audit-table { display: flex; flex-direction: column; gap: var(--space-3); }
.audit-note { margin: 0; padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-xs); }
table { width: 100%; border-collapse: collapse; border-radius: var(--radius-lg); background: var(--surface); overflow: hidden; font-size: var(--text-sm); }
th { padding: var(--space-3) var(--space-4); background: var(--primary-50); color: var(--ink-500); font-size: var(--text-xs); font-weight: 600; text-align: left; }
td { padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--line-100); color: var(--ink-700); overflow-wrap: anywhere; }
td.is-system { color: var(--ink-400); }
</style>
