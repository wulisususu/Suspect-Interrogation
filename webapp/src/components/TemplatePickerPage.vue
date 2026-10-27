<script setup lang="ts">
import { computed } from 'vue'
import { Check, ChevronRight, Plus, Search } from '@lucide/vue'
import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { coreFacts } from '../utils/factCoverage'
import EmptyState from './EmptyState.vue'

/**
 * ① 选择笔录模板（样板 P05）
 *
 * 目前后端为每个案件自动带出唯一的模板，这里如实展示该模板与预览；
 * 模板库、新建模板与空白笔录尚无后端能力，按钮保留但禁用。
 */
const props = defineProps<{
  templateKey: string | null
  facts: FactItem[]
  questions: FormalQuestion[]
}>()

const emit = defineEmits<{ confirm: [] }>()

const TEMPLATE_CATALOG: Record<string, { title: string; category: string; scene: string }> = {
  SUSPECT_INQUIRY_V1: { title: '嫌疑人询问', category: '询问', scene: '办案区 / 嫌疑人' },
}

const template = computed(() => {
  if (!props.templateKey) return null
  return TEMPLATE_CATALOG[props.templateKey] ?? { title: props.templateKey, category: '其他', scene: '—' }
})
const elements = computed(() => coreFacts(props.facts))
const ordered = computed(() => props.questions.filter((item) => item.active !== false).sort((a, b) => a.sortOrder - b.sortOrder))
const preview = computed(() => ordered.value.slice(0, 3))
</script>

<template>
  <section class="template-picker">
    <header class="picker-head">
      <div>
        <h1>① 选择笔录模板</h1>
        <p>按案件类型选定模板，决定核心要素与预设问题 · 民警自主选择</p>
      </div>
      <div class="picker-actions">
        <button type="button" class="picker-secondary" disabled title="功能待接入">跳过模板 · 空白笔录</button>
        <button type="button" class="picker-primary" :disabled="!template" @click="emit('confirm')">确认模板 · 进入建档<ChevronRight :size="16" aria-hidden="true" /></button>
      </div>
    </header>

    <div class="picker-body">
      <div class="picker-main">
        <div class="picker-toolbar">
          <label class="picker-search"><Search :size="15" aria-hidden="true" /><input type="search" placeholder="搜索模板名称 / 案由" disabled /></label>
          <span class="picker-chip is-active">全部 ({{ template ? 1 : 0 }})</span>
          <button type="button" class="picker-new" disabled title="功能待接入"><Plus :size="15" aria-hidden="true" />新建模板</button>
        </div>

        <EmptyState v-if="!template" kind="empty" title="暂无可用模板" description="案件尚未生成笔录模板，请返回案件管理重新进入" />
        <div v-else class="picker-grid">
          <article class="template-card is-selected">
            <header><span class="template-tag">{{ template.category }}</span></header>
            <h2>{{ template.title }}</h2>
            <p>{{ elements.map((item) => item.label).join('、') || '模板未声明核心要素' }}</p>
            <footer>
              <span>核心要素 {{ elements.length }} 项 · 预设问题 {{ ordered.length }} 条 · {{ template.scene }}</span>
              <button type="button" class="template-picked" disabled><Check :size="15" aria-hidden="true" />已选此模板</button>
            </footer>
          </article>
        </div>
      </div>

      <aside v-if="template" class="picker-preview" aria-label="模板预览">
        <h2>模板预览</h2>
        <p class="preview-title">{{ template.title }}</p>
        <h3>核心要素（{{ elements.length }} 项）</h3>
        <ol><li v-for="item in elements" :key="item.key">{{ item.label }}</li></ol>
        <h3>预设问法</h3>
        <ol><li v-for="item in preview" :key="item.id">{{ item.text }}</li></ol>
        <p class="preview-more">共 {{ ordered.length }} 条</p>
        <p class="preview-note">模板仅作问法参考，实际笔录顺序与内容由民警根据现场情况决定。</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.template-picker { display: flex; flex-direction: column; gap: var(--space-5); min-height: 0; padding: var(--space-6); }
.picker-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.picker-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 650; }
.picker-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.picker-actions { display: flex; gap: var(--space-3); }
.picker-primary, .picker-secondary { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 44px; padding: 0 var(--space-5); border-radius: var(--radius-md); font-size: var(--text-base); font-weight: 600; }
.picker-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.picker-secondary { border: 1px solid var(--primary-500); background: var(--surface); color: var(--primary-600); }

.picker-body { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: var(--space-5); min-height: 0; }
.picker-main { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.picker-toolbar { display: flex; align-items: center; gap: var(--space-3); }
.picker-search { display: flex; align-items: center; gap: var(--space-2); flex: 0 1 320px; min-height: 40px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--ink-400); }
.picker-search input { flex: 1; min-width: 0; border: 0; background: transparent; font-size: var(--text-sm); }
.picker-chip { padding: var(--space-2) var(--space-4); border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-sm); }
.picker-chip.is-active { background: var(--primary-600); color: var(--surface); }
.picker-new { display: inline-flex; align-items: center; gap: var(--space-1); margin-left: auto; min-height: 40px; padding: 0 var(--space-4); border: 1px solid var(--primary-500); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-sm); }

.picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--space-4); }
.template-card { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-5); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); }
.template-card.is-selected { border: 2px solid var(--primary-600); }
.template-tag { padding: 2px var(--space-2); border-radius: var(--radius-sm); background: var(--primary-100); color: var(--primary-600); font-size: var(--text-xs); }
.template-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-xl); font-weight: 650; }
.template-card p { margin: 0; color: var(--ink-500); font-size: var(--text-sm); line-height: 1.6; }
.template-card footer { display: flex; flex-direction: column; gap: var(--space-3); margin-top: auto; padding-top: var(--space-3); border-top: 1px solid var(--line-200); color: var(--ink-400); font-size: var(--text-xs); }
.template-picked { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 40px; border: 0; border-radius: var(--radius-sm); background: var(--primary-600); color: var(--surface); font-size: var(--text-sm); font-weight: 600; opacity: 1; cursor: default; }

.picker-preview { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); color: var(--ink-700); font-size: var(--text-sm); }
.picker-preview h2 { margin: 0; font-size: var(--text-lg); color: var(--ink-900); }
.picker-preview h3 { margin: var(--space-3) 0 0; color: var(--primary-600); font-size: var(--text-sm); }
.picker-preview ol { margin: 0; padding-left: var(--space-5); line-height: 1.8; }
.preview-title { margin: 0; color: var(--primary-600); }
.preview-more { margin: 0; color: var(--ink-400); font-size: var(--text-xs); }
.preview-note { margin: auto 0 0; padding: var(--space-3); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); }
</style>
