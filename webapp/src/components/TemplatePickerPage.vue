<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, ChevronRight, Plus } from '@lucide/vue'
import { TEMPLATE_CATALOG, TEMPLATE_CATEGORIES, recordSkeleton, type TemplateCatalogItem, type TemplateCategory } from '../config/templateCatalog'
import type { FactItem } from '../types/interrogation'
import type { FormalQuestion } from '../types/templateInterrogation'
import { coreFacts } from '../utils/factCoverage'
import EmptyState from './EmptyState.vue'

/**
 * ① 选择笔录模板（样板 P05）
 *
 * 模板目录来自 config/templateCatalog：本案后端带出的模板用真实要素与预设问题，
 * 其余为示例模板，选中后在预览里如实说明尚未接入。新建模板与空白笔录待接入。
 */
const props = defineProps<{
  templateKey: string | null
  facts: FactItem[]
  questions: FormalQuestion[]
}>()

const emit = defineEmits<{ confirm: [] }>()

const keyword = ref('')
const category = ref<TemplateCategory | ''>('')
const selectedId = ref('')
const showAllQuestions = ref(false)

const liveElements = computed(() => coreFacts(props.facts).map((item) => item.label))
const liveQuestions = computed(() => props.questions
  .filter((item) => item.active !== false)
  .sort((a, b) => a.sortOrder - b.sortOrder)
  .map((item) => item.text))

/** 本案后端模板以真实数据覆盖目录里的要素与问法；目录里没有的后端模板补一张卡。 */
const catalog = computed<TemplateCatalogItem[]>(() => {
  const live = (item: TemplateCatalogItem): TemplateCatalogItem => ({
    ...item,
    elements: liveElements.value.length ? liveElements.value : item.elements,
    presetQuestions: liveQuestions.value,
  })
  const items = TEMPLATE_CATALOG.map((item) => (item.backendKey && item.backendKey === props.templateKey ? live(item) : item))
  if (props.templateKey && !items.some((item) => item.backendKey === props.templateKey)) {
    items.unshift(live({
      id: props.templateKey, title: props.templateKey, category: 'other', tag: '其他', tagTone: 'neutral',
      learning: '本案模板', summary: '本案后端带出的笔录模板', elements: [], minutes: 0, scene: '—',
      presetQuestions: [], backendKey: props.templateKey,
    }))
  }
  return items
})

const backendItem = computed(() => catalog.value.find((item) => item.backendKey && item.backendKey === props.templateKey) ?? null)

watch(backendItem, (item) => {
  if (!selectedId.value) selectedId.value = item?.id ?? catalog.value[0]?.id ?? ''
}, { immediate: true })

const categoryChips = computed(() => [
  { key: '' as const, label: '全部', count: catalog.value.length },
  ...TEMPLATE_CATEGORIES.map((item) => ({ ...item, count: catalog.value.filter((entry) => entry.category === item.key).length })),
])

const visible = computed(() => {
  const term = keyword.value.trim()
  return catalog.value.filter((item) => (!category.value || item.category === category.value)
    && (!term || item.title.includes(term) || item.summary.includes(term) || item.tag.includes(term)))
})

const selected = computed(() => catalog.value.find((item) => item.id === selectedId.value) ?? null)
const isSample = computed(() => Boolean(selected.value && !selected.value.backendKey))
const previewQuestions = computed(() => {
  const list = selected.value?.presetQuestions ?? []
  return showAllQuestions.value ? list : list.slice(0, 3)
})

function choose(item: TemplateCatalogItem) {
  selectedId.value = item.id
  showAllQuestions.value = false
}

const circled = (index: number) => String.fromCharCode(0x2460 + index)
</script>

<template>
  <section class="template-picker">
    <header class="picker-head">
      <div>
        <h1>① 选择笔录模板</h1>
        <p>同类案件 3–5 份笔录即可形成固定模板 · 民警自主选择，AI 只作推荐</p>
      </div>
      <div class="picker-actions">
        <button type="button" class="picker-secondary" disabled title="功能待接入">跳过模板 · 空白笔录</button>
        <button type="button" class="picker-primary" :disabled="!selected" @click="emit('confirm')">确认模板 · 进入建档<ChevronRight :size="18" aria-hidden="true" /></button>
      </div>
    </header>

    <div class="picker-body">
      <div class="picker-main">
        <div class="picker-toolbar">
          <input v-model="keyword" class="picker-search" type="search" placeholder="搜索模板名称 / 案由" aria-label="搜索模板名称或案由" />
          <div class="picker-chips" role="tablist" aria-label="模板分类">
            <button
              v-for="chip in categoryChips"
              :key="chip.key || 'all'"
              type="button"
              role="tab"
              class="picker-chip"
              :class="{ 'is-active': category === chip.key }"
              :aria-selected="category === chip.key"
              @click="category = chip.key"
            >{{ chip.label }}（{{ chip.count }}）</button>
          </div>
          <button type="button" class="picker-new" disabled title="功能待接入"><Plus :size="16" aria-hidden="true" />新建模板</button>
        </div>

        <EmptyState v-if="!visible.length" kind="empty" title="没有匹配的模板" description="换个关键字或分类试试" />
        <div v-else class="picker-grid">
          <article v-for="item in visible" :key="item.id" class="template-card" :class="{ 'is-selected': item.id === selectedId }">
            <header>
              <span class="template-tag" :class="`is-${item.tagTone}`">{{ item.tag }}</span>
              <span v-if="item.badge" class="template-badge" :class="`is-${item.badge.tone}`">{{ item.badge.label }}</span>
              <span class="template-learning">{{ item.learning }}</span>
            </header>
            <h2>{{ item.title }}</h2>
            <p>{{ item.summary }}</p>
            <footer>
              <span class="template-meta">核心要素 {{ item.elements.length }} 项<i aria-hidden="true">·</i>预估 {{ item.minutes }} 分钟<i aria-hidden="true">·</i>{{ item.scene }}</span>
              <button v-if="item.id === selectedId" type="button" class="template-choose is-picked" aria-pressed="true"><Check :size="16" aria-hidden="true" />已选此模板</button>
              <button v-else type="button" class="template-choose" aria-pressed="false" @click="choose(item)">选此模板 →</button>
            </footer>
          </article>
        </div>
      </div>

      <aside v-if="selected" class="picker-preview" aria-label="模板预览">
        <h2>模板预览</h2>
        <p class="preview-title">{{ selected.title }}<i aria-hidden="true">·</i>{{ selected.learning }}</p>

        <h3>生成后的正本骨架</h3>
        <ol class="preview-list"><li v-for="(line, index) in recordSkeleton(selected.elements.length)" :key="line"><span>{{ circled(index) }}</span>{{ line }}</li></ol>

        <h3 class="is-ink">核心要素（{{ selected.elements.length }} 项）</h3>
        <ol class="preview-list"><li v-for="(element, index) in selected.elements" :key="element"><span>{{ circled(index) }}</span>{{ element }}</li></ol>

        <h3>预设问法（{{ selected.presetQuestions.length }} 条 · 人工与自助共用）</h3>
        <p v-if="!selected.presetQuestions.length" class="preview-empty">本模板暂无预设问法</p>
        <p v-else class="preview-questions">
          <span v-for="(question, index) in previewQuestions" :key="question">{{ circled(index) }} {{ question }}</span>
          <button
            v-if="selected.presetQuestions.length > 3"
            type="button"
            class="preview-more"
            @click="showAllQuestions = !showAllQuestions"
          >{{ showAllQuestions ? '收起' : `……（共 ${selected.presetQuestions.length} 条 · 展开查看全部）` }}</button>
        </p>

        <p class="preview-note">模板仅作问法参考，实际笔录顺序与内容由民警根据现场情况决定。</p>
        <p v-if="isSample" class="preview-note is-sample">
          示例模板：模板目录尚未接入后端，确认后本案仍按{{ backendItem ? `「${backendItem.title}」` : '已有' }}模板出题。
        </p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.template-picker { display: flex; flex-direction: column; min-height: 100%; background: var(--surface-sunken); }
.picker-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-5) var(--space-8); background: var(--surface); }
.picker-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 650; }
.picker-head p { margin: var(--space-2) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.picker-actions { display: flex; gap: var(--space-4); }
.picker-primary, .picker-secondary { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 48px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-md); font-weight: 600; }
.picker-primary { border: 0; background: var(--primary-600); color: var(--surface); box-shadow: var(--shadow-card); }
.picker-secondary { border: 1px solid var(--primary-600); background: var(--surface); color: var(--primary-600); }

.picker-body { display: grid; grid-template-columns: minmax(0, 1fr) 540px; gap: var(--space-5); padding: var(--space-5) var(--space-6) var(--space-6); }
.picker-main { display: flex; flex-direction: column; gap: var(--space-5); min-width: 0; }
.picker-toolbar { display: flex; align-items: center; gap: var(--space-4); }
.picker-search { flex: 0 1 300px; min-width: 160px; min-height: 44px; padding: 0 var(--space-3); border: 0; background: transparent; color: var(--ink-900); font-size: var(--text-sm); }
.picker-search::placeholder { color: var(--ink-300); }
.picker-chips { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.picker-chip { min-height: 44px; padding: 0 var(--space-5); border: 0; border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-sm); }
.picker-chip.is-active { background: var(--primary-600); color: var(--surface); font-weight: 600; }
.picker-new { display: inline-flex; align-items: center; gap: var(--space-1); margin-left: auto; min-height: 44px; padding: 0 var(--space-5); border: 1px solid var(--primary-600); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-md); font-weight: 600; }

.picker-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-4); }
.template-card { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-5); border: 2px solid transparent; border-radius: var(--radius-md); background: var(--surface); box-shadow: var(--shadow-card); }
.template-card.is-selected { border-color: var(--primary-600); }
.template-card > header { display: flex; align-items: center; gap: var(--space-2); }
.template-tag, .template-badge { padding: 2px var(--space-3); border-radius: var(--radius-pill); font-size: var(--text-xs); }
.template-tag.is-primary { background: var(--primary-100); color: var(--primary-600); }
.template-tag.is-danger { background: var(--danger-100); color: var(--danger-600); }
.template-tag.is-warning { background: var(--warning-100); color: var(--warning-700); }
.template-tag.is-neutral { background: var(--surface-muted); color: var(--ink-500); }
.template-badge.is-danger { background: var(--danger-600); color: var(--surface); }
.template-badge.is-success { background: var(--success-600); color: var(--surface); }
.template-badge.is-warning { background: var(--warning-100); color: var(--warning-700); }
.template-learning { margin-left: auto; color: var(--ink-400); font-size: var(--text-xs); }
.template-card h2 { margin: var(--space-2) 0 0; color: var(--ink-900); font-size: var(--text-xl); font-weight: 650; }
.template-card p { margin: 0; color: var(--ink-400); font-size: var(--text-sm); line-height: 1.7; }
.template-card footer { display: flex; flex-direction: column; gap: var(--space-4); margin-top: auto; padding-top: var(--space-4); border-top: 1px solid var(--line-200); }
.template-meta { color: var(--ink-500); font-size: var(--text-sm); }
.template-meta i, .preview-title i { margin: 0 var(--space-2); font-style: normal; }
.template-choose { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 44px; border: 1px solid var(--primary-600); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-base); font-weight: 600; }
.template-choose.is-picked { border-color: var(--primary-600); background: var(--primary-600); color: var(--surface); cursor: default; }

.picker-preview { display: flex; flex-direction: column; gap: var(--space-2); align-self: start; padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); color: var(--ink-700); font-size: var(--text-sm); }
.picker-preview h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.preview-title { margin: 0 0 var(--space-2); padding-bottom: var(--space-3); border-bottom: 1px solid var(--line-200); color: var(--primary-600); }
.picker-preview h3 { margin: var(--space-3) 0 0; color: var(--primary-600); font-size: var(--text-sm); font-weight: 650; }
.picker-preview h3.is-ink { color: var(--ink-900); }
.preview-list { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; padding: 0; list-style: none; line-height: 1.7; }
.preview-list span { margin-right: var(--space-1); }
.preview-questions { display: flex; flex-wrap: wrap; gap: var(--space-1) var(--space-5); margin: 0; line-height: 1.7; }
.preview-more { padding: 0; border: 0; background: transparent; color: var(--ink-500); font-size: var(--text-sm); }
.preview-empty { margin: 0; color: var(--ink-400); }
.preview-note { margin: var(--space-3) 0 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); line-height: 1.6; }
.preview-note.is-sample { margin-top: 0; background: var(--warning-100); color: var(--warning-700); }

@media (max-width: 1600px) { .picker-body { grid-template-columns: minmax(0, 1fr) 400px; } .picker-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 1100px) { .picker-body, .picker-grid { grid-template-columns: 1fr; } .picker-toolbar { flex-wrap: wrap; } }
</style>
