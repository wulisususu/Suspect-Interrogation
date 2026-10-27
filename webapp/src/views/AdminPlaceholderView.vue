<script setup lang="ts">
import { computed, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import RecordingPlayerShell from '../components/RecordingPlayerShell.vue'
import SignatureEnrollDialog from '../components/SignatureEnrollDialog.vue'
import type { AdminPanel } from '../utils/rootRoute'

/**
 * 尚无后端接口的后台页面（样板 P24–P28）：页头、筛选与表头按设计稿就位，
 * 数据区统一显示「功能待接入」，所有新增 / 保存操作禁用，不展示示例数据。
 */
const props = defineProps<{ kind: AdminPanel }>()
const emit = defineEmits<{ open: [panel: AdminPanel] }>()
const enrollOpen = ref(false)

interface ListScreen {
  layout: 'list'
  title: string
  subtitle: string
  createLabel: string
  categories?: string[]
  columns: string[]
}
interface PaneScreen {
  layout: 'panes'
  title: string
  subtitle: string
}

const SCREENS: Record<AdminPanel, ListScreen | PaneScreen> = {
  knowledge: { layout: 'list', title: '知识库管理', subtitle: '维护问话要点与法规条目 · 支持新增 / 修改 / 停用 / 删除', createLabel: '＋ 新增知识条目', categories: ['全部条目', '问话要点', '法规条文', '取证规范', '安全提示'], columns: ['条目标题', '分类', '状态', '更新时间', '操作'] },
  templates: { layout: 'list', title: '模板管理', subtitle: '模板版本化：停用不删除；笔录创建时复制结构快照，不随模板后续修改变化', createLabel: '＋ 新建模板', columns: ['模板名称', '案件类型', '版本', '状态', '更新时间', '操作'] },
  signatures: { layout: 'list', title: '民警签名管理（预先录入）', subtitle: '签名预先手写录入并绑定警号，签署环节一键调用；停用后不可调用但保留记录', createLabel: '＋ 新增签名', columns: ['民警', '警号', '签名样式', '录入时间', '状态', '操作'] },
  'template-edit': { layout: 'panes', title: '模板编辑', subtitle: '左侧树编辑结构（主题 / 小题 / 字段），右侧实时预览；保存为新版本，不影响历史笔录' },
  recordings: { layout: 'panes', title: '录音查看 · 双通道双文件', subtitle: '通道①问答分段录音可回听、对应转写；通道②全程录音作原始文件只做保存' },
}

const screen = computed(() => SCREENS[props.kind])
</script>

<template>
  <section class="placeholder-page">
    <header class="placeholder-head">
      <div>
        <h1>{{ screen.title }}</h1>
        <p>{{ screen.subtitle }}</p>
      </div>
      <button v-if="kind === 'templates'" type="button" class="placeholder-secondary" @click="emit('open', 'template-edit')">模板编辑器 ›</button>
      <button v-if="kind === 'template-edit'" type="button" class="placeholder-primary" disabled>保存为新版本</button>
      <button v-else-if="kind === 'signatures'" type="button" class="placeholder-primary" @click="enrollOpen = true">{{ screen.layout === 'list' ? screen.createLabel : '' }}</button>
      <button
        v-else-if="screen.layout === 'list'"
        type="button"
        class="placeholder-primary"
        disabled
        title="功能待接入"
      >{{ screen.createLabel }}</button>
    </header>

    <div v-if="screen.layout === 'list'" class="placeholder-list" :class="{ 'has-categories': screen.categories }">
      <nav v-if="screen.categories" class="placeholder-categories" aria-label="分类">
        <span v-for="(category, index) in screen.categories" :key="category" :class="{ active: index === 0 }">{{ category }}</span>
      </nav>
      <div class="placeholder-table">
        <table><thead><tr><th v-for="column in screen.columns" :key="column">{{ column }}</th></tr></thead></table>
        <EmptyState kind="pending" :title="screen.title" />
      </div>
    </div>

    <div v-else-if="kind === 'template-edit'" class="placeholder-panes">
      <article><h2>结构树</h2><EmptyState kind="pending" title="主题 / 小题 / 字段" /></article>
      <article><h2>实时预览</h2><EmptyState kind="pending" title="笔录预览" /></article>
    </div>

    <div v-else class="placeholder-panes is-recordings">
      <article>
        <h2>通道① 问答分段录音（随题回听 · 对应转写）</h2>
        <RecordingPlayerShell />
        <EmptyState kind="pending" title="分段录音" />
      </article>
      <article>
        <h2>通道② 全程录音（原始文件）</h2>
        <EmptyState kind="pending" title="全程录音" />
        <p class="placeholder-note">全程录音作为原始文件只做保存，不参与转写、不拆分、不修改；用于事后核对与防翻供</p>
        <button type="button" class="placeholder-secondary" disabled>调阅全程录音（需授权 · 留痕）</button>
      </article>
    </div>

    <SignatureEnrollDialog v-if="enrollOpen" @close="enrollOpen = false" />
  </section>
</template>

<style scoped>
.placeholder-page { display: flex; flex-direction: column; gap: var(--space-4); max-width: 1400px; margin: 0 auto; }
.placeholder-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.placeholder-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.placeholder-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.placeholder-primary, .placeholder-secondary { min-height: 44px; padding: 0 var(--space-5); border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: 600; }
.placeholder-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.placeholder-secondary { border: 1px solid var(--primary-500); background: var(--surface); color: var(--primary-600); }
.placeholder-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); }
.placeholder-list.has-categories { grid-template-columns: 200px minmax(0, 1fr); }
.placeholder-categories { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-radius: var(--radius-lg); background: var(--surface); }
.placeholder-categories span { padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-sm); }
.placeholder-categories span.active { background: var(--primary-600); color: var(--surface); }
.placeholder-table { display: flex; flex-direction: column; border-radius: var(--radius-lg); background: var(--surface); overflow: hidden; }
.placeholder-table table { width: 100%; border-collapse: collapse; }
.placeholder-table th { padding: var(--space-3) var(--space-4); background: var(--primary-50); color: var(--ink-500); font-size: var(--text-xs); font-weight: 600; text-align: left; }
.placeholder-table :deep(.empty-state) { padding: var(--space-5); }
.placeholder-panes { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-4); }
.placeholder-panes.is-recordings { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
.placeholder-panes article { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.placeholder-panes h2 { margin: 0; color: var(--primary-600); font-size: var(--text-md); font-weight: 600; }
.placeholder-note { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
@media (max-width: 1100px) { .placeholder-list.has-categories, .placeholder-panes, .placeholder-panes.is-recordings { grid-template-columns: 1fr; } }
</style>
