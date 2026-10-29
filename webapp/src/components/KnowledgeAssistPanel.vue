<script setup lang="ts">
/**
 * 办案页知识提示（③ 问答录入右栏）
 *
 * 两种用法，都只“提示”，不写笔录：
 *  1. 按当前题目/要素匹配知识条目，展示来源与版本，必要时提示同音错写；
 *  2. 由已验证条目给出建议问法，民警点「采纳」才通过现有的建题接口生成 LIVE 草稿题。
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchDraftQuestions,
  fetchGuidance,
  lookupTermCorrections,
  type DraftQuestion,
  type GuidanceItem,
} from '../api/knowledge'
import type { FormalQuestion } from '../types/templateInterrogation'

const props = withDefaults(defineProps<{
  caseId: string
  questions: FormalQuestion[]
  recordingQuestionId?: string | null
  liveText?: string
  locked?: boolean
}>(), { recordingQuestionId: null, liveText: '', locked: false })

const emit = defineEmits<{ useSuggestion: [text: string] }>()

const guidance = ref<GuidanceItem[]>([])
const drafts = ref<DraftQuestion[]>([])
const corrections = ref<Array<{ wrong: string; right: string }>>([])
const loading = ref(false)
const error = ref('')
const expanded = ref(true)
const showDrafts = ref(false)

const target = computed<FormalQuestion | null>(() => {
  if (props.recordingQuestionId) {
    const recording = props.questions.find((item) => item.id === props.recordingQuestionId)
    if (recording) return recording
  }
  return props.questions.find((item) => item.active && !item.formalAnswerText.trim()) ?? props.questions[0] ?? null
})

const targetLabel = computed(() => (target.value ? target.value.text.slice(0, 40) : '未选择题目'))

async function loadGuidance() {
  if (!props.caseId) return
  loading.value = true
  error.value = ''
  try {
    guidance.value = await fetchGuidance({
      caseId: props.caseId,
      ...(target.value ? { questionId: target.value.id } : {}),
      ...(target.value?.elementKey ? { elementKey: target.value.elementKey } : {}),
      limit: 4,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '知识提示读取失败'
  } finally {
    loading.value = false
  }
}

async function loadCorrectionHint() {
  if (!props.liveText?.trim()) {
    corrections.value = []
    return
  }
  try {
    corrections.value = await lookupTermCorrections(props.liveText)
  } catch {
    corrections.value = []
  }
}

async function askDrafts() {
  showDrafts.value = true
  drafts.value = []
  try {
    drafts.value = await fetchDraftQuestions({
      caseId: props.caseId,
      ...(target.value ? { questionId: target.value.id } : {}),
      ...(target.value?.elementKey ? { elementKey: target.value.elementKey } : {}),
      limit: 3,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '建议问法生成失败'
  }
}

function adopt(text: string) {
  if (props.locked) return
  emit('useSuggestion', text)
  showDrafts.value = false
}

watch(() => target.value?.id, () => { void loadGuidance(); drafts.value = [] })
watch(() => props.liveText, () => { void loadCorrectionHint() })

onMounted(() => {
  void loadGuidance()
  void loadCorrectionHint()
})
</script>

<template>
  <section class="knowledge-assist" aria-label="知识提示">
    <header>
      <button type="button" class="toggle" @click="expanded = !expanded">
        <strong>知识提示</strong>
        <span v-if="guidance.length" class="count">{{ guidance.length }}</span>
        <span class="target">{{ targetLabel }}</span>
      </button>
      <button type="button" class="ghost" :disabled="locked" @click="askDrafts">建议问法</button>
    </header>

    <div v-if="expanded" class="body">
      <p v-if="corrections.length" class="correction" role="status">
        识别到
        <template v-for="(item, index) in corrections" :key="item.wrong">
          <em>{{ item.wrong }}</em><template v-if="index < corrections.length - 1">、</template>
        </template>
        ，规范写法应为
        <strong>{{ [...new Set(corrections.map((item) => item.right))].join('、') }}</strong>，提交前请核对。
      </p>

      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <p v-else-if="loading" class="hint">正在匹配知识…</p>
      <p v-else-if="!guidance.length" class="hint">暂无与本题相关的知识条目。</p>

      <ul v-else class="cards">
        <li v-for="item in guidance" :key="item.id">
          <div class="card-head">
            <strong>{{ item.title }}</strong>
            <span class="badge" :class="item.status === 'verified' ? 'ok' : 'warn'">
              {{ item.status === 'verified' ? '已验证' : '待确认' }}
            </span>
          </div>
          <p class="snippet">{{ item.snippet }}</p>
          <p class="meta">
            {{ item.categoryName }} · v{{ item.version }}
            <template v-if="item.sourceRef"> · 溯源 {{ item.sourceRef }}</template>
          </p>
        </li>
      </ul>

      <div v-if="showDrafts" class="drafts">
        <p class="hint">以下问法来自已验证知识，采纳后只生成草稿题，不写笔录。</p>
        <ul>
          <li v-for="(item, index) in drafts" :key="`${item.entryId}-${index}`">
            <span>{{ item.text }}</span>
            <button type="button" :disabled="locked" @click="adopt(item.text)">采纳</button>
            <small v-if="item.entryTitle">来源：{{ item.entryTitle }} v{{ item.entryVersion ?? '—' }}</small>
          </li>
        </ul>
        <p v-if="!drafts.length" class="hint">没有可用的建议问法。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.knowledge-assist { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
.knowledge-assist header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.toggle { display: flex; align-items: center; gap: var(--space-2); border: 0; background: transparent; color: var(--ink-800); font-size: var(--text-sm); cursor: pointer; padding: 0; }
.count { padding: 0 6px; border-radius: 999px; background: var(--primary-50); color: var(--primary-700); font-size: var(--text-xs); }
.target { color: var(--ink-400); font-size: var(--text-xs); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.body { display: flex; flex-direction: column; gap: var(--space-2); }
.correction { margin: 0; padding: var(--space-2); border-radius: var(--radius-md); background: var(--warning-50); color: var(--warning-700); font-size: var(--text-xs); }
.correction em { font-style: normal; font-weight: 600; }
.hint, .err { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.err { color: var(--danger-700); }
.cards { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.cards li { padding: var(--space-2); border: 1px solid var(--line-200); border-radius: var(--radius-md); background: var(--surface-sunken); }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.card-head strong { color: var(--ink-800); font-size: var(--text-sm); }
.badge { padding: 1px 8px; border-radius: 999px; font-size: var(--text-xs); }
.badge.ok { background: var(--success-50); color: var(--success-700); }
.badge.warn { background: var(--warning-50); color: var(--warning-700); }
.snippet { margin: 4px 0; color: var(--ink-600); font-size: var(--text-xs); line-height: 1.6; }
.meta { margin: 0; color: var(--ink-400); font-size: var(--text-xs); }
.drafts { display: flex; flex-direction: column; gap: var(--space-2); padding-top: var(--space-2); border-top: 1px dashed var(--line-300); }
.drafts ul { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.drafts li { display: grid; grid-template-columns: 1fr auto; gap: 4px var(--space-2); align-items: center; padding: var(--space-2); border-radius: var(--radius-md); background: var(--primary-50); }
.drafts li span { color: var(--ink-800); font-size: var(--text-sm); }
.drafts li small { grid-column: 1 / -1; color: var(--ink-500); font-size: var(--text-xs); }
.drafts button { min-height: 30px; padding: 0 var(--space-3); border: 0; border-radius: var(--radius-md); background: var(--primary-600); color: var(--surface); font-size: var(--text-xs); cursor: pointer; }
.ghost { min-height: 32px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-700); font-size: var(--text-xs); cursor: pointer; }
.ghost:disabled { opacity: 0.6; cursor: default; }
</style>
