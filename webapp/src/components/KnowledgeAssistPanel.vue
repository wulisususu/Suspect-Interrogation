<script setup lang="ts">
/**
 * 题后知识提示 + 智能追问助手（③ 问答录入；设计稿 P24「问话时由系统自动调用并附在题后」）
 *
 * 挂在当前题卡里，不单独占一栏、不用点按钮：
 *  - 智能追问助手：按本案模板要素里尚未确认的事实，推荐已审核知识里的问法。民警点「采纳」由后端
 *    建一张 LIVE 草稿题（不写正式答案），点「不适用」只记反馈；两种操作都留痕，重复点击不重复计数。
 *  - 依据：按这道题和刚才的回答匹配到的已验证知识，显示可核对的出处；过期或被取代的条目后端已不返回。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { BookOpen, Sparkles } from '@lucide/vue'
import {
  fetchGuidance,
  fetchSuggestions,
  formatCitation,
  lookupTermCorrections,
  sendSuggestionFeedback,
  type GuidanceItem,
  type Suggestion,
  type SuggestionResult,
} from '../api/knowledge'

const props = withDefaults(defineProps<{
  caseId: string
  questionId: string
  elementKey?: string | null
  /** 这道题刚才的回答：录音中为实时转写，录完为草稿 / 正本文字 */
  contextText?: string
  /** 题目或答案变了（采纳成题、摘入正本……）就加 1，让推荐重新按要素状态计算 */
  revision?: number
  locked?: boolean
}>(), { elementKey: null, contextText: '', revision: 0, locked: false })

/** 采纳交给父组件走题目 store（建题后刷新草稿栏）；不适用在这里直接上报。 */
const emit = defineEmits<{ adopt: [key: string] }>()

/** 回答还在变（边录边转）时等停顿再查，避免每个字都请求一次。 */
const CONTEXT_DEBOUNCE_MS = 1200
/** 只取回答最后一段参与匹配：刚说的内容最能说明接下来该问什么。 */
const CONTEXT_CHARS = 300

const guidance = ref<GuidanceItem[]>([])
const assistant = ref<SuggestionResult | null>(null)
const handled = ref<Set<string>>(new Set())
const corrections = ref<Array<{ wrong: string; right: string }>>([])
const openId = ref<string | null>(null)
const error = ref('')
let ticket = 0
let timer: ReturnType<typeof setTimeout> | undefined

const suggestions = computed(() => (assistant.value?.suggestions ?? []).filter((item) => !handled.value.has(item.key)))
// 没有可推荐的问法时不单独显示「X 尚未确认」：缺项已在要素覆盖条上，程式题卡上再提示只是噪音。
const showAssistant = computed(() => suggestions.value.length > 0)
const hasContent = computed(() => showAssistant.value || guidance.value.length > 0 || corrections.value.length > 0 || !!error.value)

async function refresh() {
  if (!props.caseId || !props.questionId) return
  const current = ++ticket
  const q = props.contextText.trim().slice(-CONTEXT_CHARS)
  const scope = { caseId: props.caseId, questionId: props.questionId, ...(q ? { q } : {}) }
  try {
    const [matched, recommended, fixes] = await Promise.all([
      fetchGuidance({ ...scope, ...(props.elementKey ? { elementKey: props.elementKey } : {}), limit: 3 }),
      fetchSuggestions({ ...scope, limit: 3 }),
      q ? lookupTermCorrections(q).catch(() => []) : Promise.resolve([]),
    ])
    if (current !== ticket) return
    guidance.value = matched
    assistant.value = recommended
    handled.value = new Set()
    corrections.value = fixes
    error.value = ''
  } catch (err) {
    if (current !== ticket) return
    error.value = err instanceof Error ? err.message : '知识提示读取失败'
  }
}

function sourceText(item: Suggestion) {
  return `${item.entryTitle} v${item.entryVersion}${item.sourceRef ? ` · ${item.sourceRef}` : ''}`
}

function adopt(item: Suggestion) {
  if (props.locked) return
  handled.value = new Set([...handled.value, item.key])
  emit('adopt', item.key)
}

async function dismiss(item: Suggestion) {
  if (props.locked) return
  handled.value = new Set([...handled.value, item.key])
  try {
    await sendSuggestionFeedback({ caseId: props.caseId, key: item.key, action: 'NOT_APPLICABLE' })
    void refresh()
  } catch (err) {
    handled.value = new Set([...handled.value].filter((key) => key !== item.key))
    error.value = err instanceof Error ? err.message : '反馈提交失败'
  }
}

function toggle(entryId: string) {
  openId.value = openId.value === entryId ? null : entryId
}

watch(() => props.questionId, () => {
  clearTimeout(timer)
  openId.value = null
  guidance.value = []
  assistant.value = null
  corrections.value = []
  void refresh()
}, { immediate: true })

watch(() => [props.contextText, props.revision], () => {
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

    <div v-if="showAssistant && assistant" class="ck-assistant" aria-label="智能追问助手">
      <header class="ck-assistant-head">
        <Sparkles :size="14" aria-hidden="true" />
        <strong>智能追问助手</strong>
        <span v-if="assistant.templateTitle">{{ assistant.templateTitle }} · 当前案件</span>
      </header>
      <div v-if="assistant.focus" class="ck-focus">
        <p class="ck-focus-title"><strong>{{ assistant.focus.label }} · {{ assistant.focus.statusText }}</strong><span class="ck-tag">需要核实</span></p>
        <p class="ck-focus-hint">{{ assistant.focus.hint }}</p>
      </div>
      <ul v-if="suggestions.length" class="ck-suggestions">
        <li v-for="item in suggestions" :key="item.key">
          <span class="ck-label">推荐追问<template v-if="item.elementLabel && item.elementKey !== assistant.focus?.elementKey"> · {{ item.elementLabel }}</template></span>
          <p class="ck-question">“{{ item.text }}”</p>
          <small class="ck-source">来源：{{ sourceText(item) }}<template v-if="item.usage.adopted"> · 已在 {{ item.usage.adopted }} 个案件中被采纳</template></small>
          <div class="ck-actions">
            <button type="button" class="ck-adopt" :disabled="locked" @click="adopt(item)">采纳</button>
            <button type="button" class="ck-dismiss" :disabled="locked" @click="dismiss(item)">不适用</button>
          </div>
        </li>
      </ul>
      <small class="ck-note">所有问题由民警选择，采纳只生成草稿题，不会自动写入正式笔录。</small>
    </div>

    <ul v-if="guidance.length" class="ck-entries" aria-label="依据">
      <li v-for="item in guidance" :key="item.id">
        <button type="button" class="ck-entry" :aria-expanded="openId === item.id" @click="toggle(item.id)">
          <BookOpen :size="14" aria-hidden="true" />
          <span class="ck-category">{{ item.categoryName }}</span>
          <strong>{{ item.title }}</strong>
        </button>
        <div v-if="openId === item.id" class="ck-detail">
          <p>{{ item.snippet }}</p>
          <small>v{{ item.version }}<template v-if="formatCitation(item)"> · 依据 {{ formatCitation(item) }}</template><template v-if="item.matchReasons?.length"> · {{ item.matchReasons[0] }}</template></small>
        </div>
      </li>
    </ul>

    <p v-if="error" class="ck-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.card-knowledge { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); padding: var(--space-2) var(--space-3); border-top: 1px dashed var(--line-300); }
.ck-correction { margin: 0; padding: 6px var(--space-2); border-radius: var(--radius-md); background: var(--warning-50); color: var(--warning-700); font-size: var(--text-xs); }
.ck-correction em { font-style: normal; text-decoration: line-through; }
.ck-assistant { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--primary-200); border-radius: var(--radius-md); background: var(--primary-50); }
.ck-assistant-head { display: flex; align-items: center; gap: 6px; color: var(--primary-700); font-size: var(--text-xs); }
.ck-assistant-head strong { font-size: var(--text-sm); }
.ck-assistant-head span { color: var(--ink-500); }
.ck-focus { padding: 6px var(--space-2); border-radius: var(--radius-md); background: var(--surface); }
.ck-focus-title { display: flex; align-items: center; gap: var(--space-2); margin: 0; color: var(--ink-800); font-size: var(--text-sm); }
.ck-tag { padding: 0 6px; border-radius: 999px; background: var(--warning-50); color: var(--warning-700); font-size: var(--text-xs); }
.ck-focus-hint { margin: 4px 0 0; color: var(--ink-500); font-size: var(--text-xs); line-height: 1.6; }
.ck-suggestions { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.ck-suggestions li { display: flex; flex-direction: column; gap: 4px; padding: 6px var(--space-2); border-radius: var(--radius-md); background: var(--surface); }
.ck-label { color: var(--ink-500); font-size: var(--text-xs); }
.ck-question { margin: 0; color: var(--ink-800); font-size: var(--text-sm); line-height: 1.6; }
.ck-source { color: var(--ink-400); font-size: var(--text-xs); }
.ck-actions { display: flex; gap: var(--space-2); }
.ck-adopt, .ck-dismiss { min-height: 30px; padding: 0 var(--space-3); border-radius: var(--radius-md); font-size: var(--text-xs); cursor: pointer; }
.ck-adopt { border: 0; background: var(--primary-600); color: var(--surface); }
.ck-dismiss { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-600); }
.ck-adopt:disabled, .ck-dismiss:disabled { opacity: 0.6; cursor: default; }
.ck-note { color: var(--ink-400); font-size: var(--text-xs); }
.ck-entries { display: flex; flex-direction: column; gap: 4px; margin: 0; padding: 0; list-style: none; }
.ck-entry { display: flex; align-items: center; gap: 6px; width: 100%; min-height: 30px; padding: 0; border: 0; background: transparent; color: var(--ink-700); font-size: var(--text-xs); text-align: left; cursor: pointer; }
.ck-entry strong { overflow: hidden; color: var(--ink-800); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.ck-category { flex: none; padding: 0 6px; border-radius: 999px; background: var(--primary-50); color: var(--primary-700); }
.ck-detail { padding: 6px var(--space-2); border-radius: var(--radius-md); background: var(--surface-sunken); }
.ck-detail p { margin: 0 0 4px; color: var(--ink-600); font-size: var(--text-xs); line-height: 1.6; }
.ck-detail small { color: var(--ink-400); font-size: var(--text-xs); }
.ck-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); }
</style>
