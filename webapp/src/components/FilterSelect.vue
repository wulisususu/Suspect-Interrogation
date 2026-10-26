<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'

/**
 * 筛选下拉框
 *
 * 替代原先的胶囊组：收起 / 展开 / 聚焦三态，选中项浅蓝高亮。
 * 单选与多选共用一套外观，避免同类筛选长得不一样。
 */
export interface FilterOption {
  key: string
  label: string
  count?: number
}

const props = withDefaults(defineProps<{
  label: string
  options: FilterOption[]
  modelValue: string | string[]
  multiple?: boolean
  allLabel?: string
}>(), { multiple: false, allLabel: '全部' })

const emit = defineEmits<{ 'update:modelValue': [value: string | string[]] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const selected = computed<string[]>(() => (Array.isArray(props.modelValue) ? props.modelValue : [props.modelValue]))
const summary = computed(() => {
  const picked = props.options.filter((option) => selected.value.includes(option.key))
  if (!picked.length) return props.allLabel
  if (!props.multiple) return picked[0]!.label
  return picked.length === 1 ? picked[0]!.label : `${picked[0]!.label} 等 ${picked.length} 项`
})
const isActive = computed(() => selected.value.length > 0 && !(selected.value.length === 1 && selected.value[0] === ''))

function togglePanel() {
  open.value = !open.value
}

function pick(option: FilterOption) {
  if (!props.multiple) {
    emit('update:modelValue', option.key)
    open.value = false
    return
  }
  const next = selected.value.includes(option.key)
    ? selected.value.filter((key) => key !== option.key)
    : [...selected.value, option.key]
  emit('update:modelValue', next)
}

function onDocumentPointer(event: PointerEvent) {
  if (!open.value) return
  if (root.value && !root.value.contains(event.target as Node)) open.value = false
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    open.value = false
    event.stopPropagation()
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointer)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointer)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="filter-select" :class="{ 'is-open': open, 'is-active': isActive }">
    <button
      type="button"
      class="filter-trigger"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="togglePanel"
    >
      <span class="filter-label">{{ label }}</span>
      <span class="filter-summary">{{ summary }}</span>
      <ChevronDown :size="15" class="filter-chevron" aria-hidden="true" />
    </button>

    <ul v-if="open" class="filter-panel" role="listbox" :aria-multiselectable="multiple || undefined">
      <li v-if="!multiple">
        <button type="button" role="option" class="filter-option" :class="{ selected: !isActive }" :aria-selected="!isActive" @click="emit('update:modelValue', '')">
          <span>{{ allLabel }}</span>
          <Check v-if="!isActive" :size="15" aria-hidden="true" />
        </button>
      </li>
      <li v-for="option in options" :key="option.key">
        <button
          type="button"
          role="option"
          class="filter-option"
          :class="{ selected: selected.includes(option.key) }"
          :aria-selected="selected.includes(option.key)"
          @click="pick(option)"
        >
          <span>{{ option.label }}<em v-if="option.count !== undefined">{{ option.count }}</em></span>
          <Check v-if="selected.includes(option.key)" :size="15" aria-hidden="true" />
        </button>
      </li>
      <li v-if="!options.length" class="filter-empty">暂无可选项</li>
    </ul>
  </div>
</template>

<style scoped>
.filter-select { position: relative; flex: 0 0 auto; }

.filter-trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 38px;
  padding: 0 var(--space-3);
  border: 1px solid var(--line-300);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--ink-500);
  font-size: var(--text-sm);
  white-space: nowrap;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}
.filter-trigger:hover { border-color: var(--primary-200); }
.filter-select.is-active .filter-trigger { border-color: var(--primary-200); background: var(--primary-50); }
.filter-select.is-open .filter-trigger { border-color: var(--primary-500); box-shadow: var(--shadow-focus); }

.filter-label { color: var(--ink-400); }
.filter-summary { color: var(--ink-900); font-weight: 600; }
.filter-select.is-active .filter-summary { color: var(--primary-700); }
.filter-chevron { color: var(--ink-300); transition: transform 0.16s ease; }
.filter-select.is-open .filter-chevron { transform: rotate(180deg); color: var(--primary-600); }

.filter-panel {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  left: 0;
  min-width: 100%;
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: var(--space-1);
  list-style: none;
  border: 1px solid var(--line-200);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-pop);
}

.filter-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
  min-height: 38px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-700);
  font-size: var(--text-sm);
  text-align: left;
  white-space: nowrap;
}
.filter-option:hover { background: var(--surface-sunken); }
.filter-option.selected { background: var(--primary-100); color: var(--primary-700); font-weight: 600; }
.filter-option em { margin-left: var(--space-2); color: var(--ink-300); font-style: normal; font-size: var(--text-xs); }

.filter-empty { padding: var(--space-3); color: var(--ink-300); font-size: var(--text-sm); text-align: center; }
</style>
