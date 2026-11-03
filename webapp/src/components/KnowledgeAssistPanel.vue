<script setup lang="ts">
/**
 * 题后知识提示（③ 问答录入；设计稿 P24「问话时由系统自动调用并附在题后」）
 *
 * 挂在当前题卡里，不单独占一栏、不用点按钮：按这道题、它的要素和刚才的回答自动匹配已验证知识，
 * 给出依据与建议追问。只提示，不写笔录；点追问才通过现有建题接口在本题之后加一张草稿题卡。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { BookOpen, Plus } from '@lucide/vue'
import {
  fetchDraftQuestions,
  fetchGuidance,
  lookupTermCorrections,
  type DraftQuestion,
  type GuidanceItem,
} from '../api/knowledge'

const props = withDefaults(defineProps<{
  caseId: string
  questionId: string
  elementKey?: string | null
  /** 这道题刚才的回答：录音中为实时转写，录完为草稿 / 正本文字 */
  contextText?: string
  locked?: boolean
}>(), { elementKey: null, contextText: '', locked: false })

const emit = defineEmits<{ adopt: [text: string] }>()

/** 回答还在变（边录边转）时等停顿再查，避免每个字都请求一次。 */
const CONTEXT_DEBOUNCE_MS = 1200
/** 只取回答最后一段参与匹配：刚说的内容最能说明接下来该问什么。 */
const CONTEXT_CHARS = 300

const guidance = ref<GuidanceItem[]>([])
const drafts = ref<DraftQuestion[]>([])
const corrections = ref<Array<{ wrong: string; right: string }>>([])
const openId = ref<string | null>(null)
const error = ref('')
let ticket = 0
let timer: ReturnType<typeof setTimeout> | undefined

const hasContent = computed(() => guidance.value.length > 0 || drafts.value.length > 0 || corrections.value.length > 0 || !!error.value)

async function refresh() {
  if (!props.caseId || !props.questionId) return
  const current = ++ticket
  const q = props.contextText.trim().slice(-CONTEXT_CHARS)
  const scope = {
    caseId: props.caseId,
    questionId: props.questionId,
    ...(props.elementKey ? { elementKey: props.elementKey } : {}),
    ...(q ? { q } : {}),
  }
  try {
    const [matched, suggested, fixes] = await Promise.all([
      fetchGuidance({ ...scope, limit: 3 }),
      fetchDraftQuestions({ ...scope, limit: 3 }),
      q ? lookupTermCorrections(q).catch(() => []) : Promise.resolve([]),
    ])
    if (current !== ticket) return
    guidance.value = matched
    drafts.value = suggested
    corrections.value = fixes
    error.value = ''
  } catch (err) {
    if (current !== ticket) return
    error.value = err instanceof Error ? err.message : '知识提示读取失败'
  }
}

function toggle(entryId: string) {
  openId.value = openId.value === entryId ? null : entryId
}

function adopt(item: DraftQuestion) {
  if (props.locked) return
  emit('adopt', item.text)
  drafts.value = drafts.value.filter((draft) => draft !== item)
}

watch(() => props.questionId, () => {
  clearTimeout(timer)
  openId.value = null
  guidance.value = []
  drafts.value = []
  corrections.value = []
  void refresh()
}, { immediate: true })

watch(() => props.contextText, () => {
  clearTimeout(timer)
  timer = setTimeout(() => { void refresh() }, CONTEXT_DEBOUNCE_MS)
})

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <section v-if="hasContent" class="card-knowledge" aria-label="题后知识提示" @click.stop>
    <p v-if="corrections.length" class="ck-correction" role="status">
      纠错：<template v-for="(item, index) in corrections" :key="item.wrong"><em>{{ item.wrong }}</em> → <strong>{{ item.right }}</strong><template v-if="index < corrections.length - 1">、</template></template>
      · 同音字待核对
    </p>

    <ul v-if="guidance.length" class="ck-entries">
      <li v-for="item in guidance" :key="item.id">
        <button type="button" class="ck-entry" :aria-expanded="openId === item.id" @click="toggle(item.id)">
          <BookOpen :size="14" aria-hidden="true" />
          <span class="ck-category">{{ item.categoryName }}</span>
          <strong>{{ item.title }}</strong>
        </button>
        <div v-if="openId === item.id" class="ck-detail">
          <p>{{ item.snippet }}</p>
          <small>v{{ item.version }}<template v-if="item.sourceRef"> · 依据 {{ item.sourceRef }}</template><template v-if="item.matchReasons?.length"> · {{ item.matchReasons[0] }}</template></small>
        </div>
      </li>
    </ul>

    <div v-if="drafts.length" class="ck-drafts">
      <span class="ck-label">建议追问</span>
      <button
        v-for="(item, index) in drafts"
        :key="`${item.entryId}-${index}`"
        type="button"
        class="ck-draft"
        :disabled="locked"
        :title="item.entryTitle ? `依据：${item.entryTitle}${item.entryVersion ? ` v${item.entryVersion}` : ''} · 点击在本题后追加一问` : '点击在本题后追加一问'"
        @click="adopt(item)"
      ><Plus :size="14" aria-hidden="true" />{{ item.text }}</button>
    </div>

    <p v-if="error" class="ck-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.card-knowledge { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); padding: var(--space-2) var(--space-3); border-top: 1px dashed var(--line-300); }
.ck-correction { margin: 0; padding: 6px var(--space-2); border-radius: var(--radius-md); background: var(--warning-50); color: var(--warning-700); font-size: var(--text-xs); }
.ck-correction em { font-style: normal; text-decoration: line-through; }
.ck-entries { display: flex; flex-direction: column; gap: 4px; margin: 0; padding: 0; list-style: none; }
.ck-entry { display: flex; align-items: center; gap: 6px; width: 100%; min-height: 30px; padding: 0; border: 0; background: transparent; color: var(--ink-700); font-size: var(--text-xs); text-align: left; cursor: pointer; }
.ck-entry strong { overflow: hidden; color: var(--ink-800); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.ck-category { flex: none; padding: 0 6px; border-radius: 999px; background: var(--primary-50); color: var(--primary-700); }
.ck-detail { padding: 6px var(--space-2); border-radius: var(--radius-md); background: var(--surface-sunken); }
.ck-detail p { margin: 0 0 4px; color: var(--ink-600); font-size: var(--text-xs); line-height: 1.6; }
.ck-detail small { color: var(--ink-400); font-size: var(--text-xs); }
.ck-drafts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.ck-label { color: var(--ink-500); font-size: var(--text-xs); }
.ck-draft { display: inline-flex; align-items: center; gap: 4px; min-height: 30px; max-width: 100%; padding: 0 var(--space-3); border: 1px dashed var(--primary-200); border-radius: var(--radius-md); background: var(--primary-50); color: var(--primary-700); font-size: var(--text-xs); text-align: left; cursor: pointer; }
.ck-draft:disabled { opacity: 0.6; cursor: default; }
.ck-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); }
</style>
