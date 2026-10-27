<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, ChevronDown, FileText } from '@lucide/vue'
import { armDrop } from '../composables/pendingDrop'
import { canConfirmFragment, confirmationCandidates, fragmentNeedsReview, orderedReviewFragments } from '../utils/recordCompletion'
import type { TemporaryAsrFragment, TemporaryAsrSpeaker } from '../types/interrogation'
import type { FormalQAUnit, QAUnitResolution } from '../types/templateInterrogation'

const props = defineProps<{ fragments: TemporaryAsrFragment[]; qaUnits: FormalQAUnit[]; busy: boolean; frozen: boolean }>()
const emit = defineEmits<{
  confirm: [ids: string[]]
  discard: [id: string]
  resolveQaUnit: [id: string, resolution: QAUnitResolution]
  correct: [id: string, speaker: TemporaryAsrSpeaker, reason: string, text: string]
}>()
const uncertainFirst = ref(true)
const selected = ref<string[]>([])
const correctionRoles = ref<Record<string, TemporaryAsrSpeaker>>({})
const correctionReasons = ref<Record<string, string>>({})
const correctionTexts = ref<Record<string, string>>({})
const fragments = computed(() => orderedReviewFragments(props.fragments, uncertainFirst.value))
const confirmed = computed(() => fragments.value.filter(item => item.state === 'CONFIRMED').length)
const candidates = computed(() => confirmationCandidates(fragments.value))
const pendingUnits = computed(() => props.qaUnits.filter(item => ['OPEN', 'CLOSED', 'ROUTING', 'NEEDS_REVIEW'].includes(item.status)))
watch(() => props.fragments, () => {
  selected.value = selected.value.filter(id => props.fragments.some(item => item.id === id && canConfirmFragment(item)))
}, { deep: true })
function toggle(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
}
function selectHighConfidence() { selected.value = candidates.value.map(item => item.id) }
function selectFragment(item: TemporaryAsrFragment) {
  if (props.frozen || props.busy) return
  armDrop([{ mime: 'application/x-formal-answer-fragments', data: JSON.stringify({ fragmentIds: [item.id], text: item.editedText || item.rawText }) }], '复核片段')
}
function relativeTime(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
function speakerLabel(speaker: TemporaryAsrSpeaker) {
  return ({ SUSPECT: '嫌疑人', INTERROGATOR: '主审民警', RECORDER: '记录民警', OFFICER_FALLBACK: '民警待核对', UNKNOWN: '身份待确认' })[speaker]
}
function confidenceLabel(item: TemporaryAsrFragment) {
  return item.confidenceSource === 'UNAVAILABLE' || item.confidence == null ? 'ASR 置信度未提供' : `ASR 置信度 ${Math.round(item.confidence * 100)}%`
}
function correct(item: TemporaryAsrFragment) {
  const reason = (correctionReasons.value[item.id] || '').trim()
  const text = (correctionTexts.value[item.id] ?? (item.editedText || item.rawText)).trim()
  if (props.frozen || props.busy || !reason || !text) return
  emit('correct', item.id, correctionRoles.value[item.id] || item.speaker, reason, text)
}
</script>

<template>
  <aside class="record-review-panel" aria-label="识别片段复核">
    <header class="review-panel-heading"><div><h2>识别片段</h2><span>已确认 {{ confirmed }} / {{ fragments.length }}</span></div><div class="review-sort"><button :class="{ active: uncertainFirst }" :aria-pressed="uncertainFirst" @click="uncertainFirst = true">待核对优先</button><button :class="{ active: !uncertainFirst }" :aria-pressed="!uncertainFirst" @click="uncertainFirst = false">按时间</button></div></header>
    <div v-if="!frozen" class="review-batch"><button :disabled="busy || !candidates.length" @click="selectHighConfidence">选择高置信 {{ candidates.length }} 条</button><button class="primary" :disabled="busy || !selected.length" @click="emit('confirm', [...selected])">确认所选 {{ selected.length || '' }}</button></div>
    <p class="review-instruction">确认转写后，选择片段，再点击左侧的“问”或“答”栏关联笔录。</p>
    <div class="review-fragments">
      <p v-if="!fragments.length" class="review-empty"><FileText :size="28" />暂无可复核的转写片段</p>
      <article v-for="item in fragments" :key="item.id" class="review-fragment" :class="{ uncertain: fragmentNeedsReview(item) && item.state !== 'CONFIRMED', confirmed: item.state === 'CONFIRMED' }">
        <header><label class="fragment-select"><input v-if="!frozen" type="checkbox" :aria-label="`选择转写片段 ${item.ordinal}`" :checked="selected.includes(item.id)" :disabled="busy || !canConfirmFragment(item)" @change="toggle(item.id)" /><time>{{ relativeTime(item.startedAtMs) }}</time></label><span>{{ speakerLabel(item.speaker) }}</span><span class="fragment-state"><Check v-if="item.state === 'CONFIRMED'" :size="14" />{{ item.state === 'CONFIRMED' ? '已确认' : fragmentNeedsReview(item) ? '待核对' : '待确认' }}</span></header>
        <p class="fragment-confidence">{{ confidenceLabel(item) }}</p><p class="fragment-text">{{ item.editedText || item.rawText || '空白片段' }}</p>
        <div v-if="!frozen" class="fragment-actions"><button :disabled="busy || !(item.editedText || item.rawText).trim()" @click="selectFragment(item)">选入笔录</button><button :disabled="busy || !canConfirmFragment(item)" @click="emit('confirm', [item.id])">确认转写</button></div>
        <details class="fragment-revision"><summary>原文与人工修正<ChevronDown :size="14" /></summary><p><strong>原始转写：</strong>{{ item.rawText || '无文字' }}</p><p v-for="revision in item.recognitionRevisions" :key="revision.revisionId">修订 {{ revision.revisionNo }} · {{ revision.reason || '未提供原因' }}<br />{{ revision.beforeText }} → {{ revision.afterText }}</p><div v-if="!frozen && item.state !== 'CONFIRMED'" class="review-correction"><label>说话人<select v-model="correctionRoles[item.id]" :aria-label="`片段 ${item.ordinal} 的说话人`" :disabled="busy"><option :value="undefined">保持：{{ speakerLabel(item.speaker) }}</option><option value="SUSPECT">嫌疑人</option><option value="INTERROGATOR">主审民警</option><option value="RECORDER">记录民警</option><option value="UNKNOWN">身份待确认</option></select></label><label>转写文字<textarea :value="correctionTexts[item.id] ?? (item.editedText || item.rawText)" :disabled="busy" :aria-label="`片段 ${item.ordinal} 的修正文字`" rows="3" @input="correctionTexts[item.id] = ($event.target as HTMLTextAreaElement).value" /></label><input v-model="correctionReasons[item.id]" :disabled="busy" :aria-label="`片段 ${item.ordinal} 的修正原因`" placeholder="填写人工修正原因（必填）" maxlength="512" /><button :disabled="busy || !(correctionReasons[item.id] || '').trim()" @click="correct(item)">保存修正</button><button class="discard" :disabled="busy" @click="emit('discard', item.id)">丢弃此段转写</button></div></details>
      </article>
      <section v-if="pendingUnits.length" class="review-qa-units"><h3>待处理问答 · {{ pendingUnits.length }}</h3><article v-for="unit in pendingUnits" :key="unit.id"><p><strong>问：</strong>{{ unit.rawQuestionText || '尚未形成问题' }}</p><p><strong>答：</strong>{{ unit.rawAnswerText || '尚无回答' }}</p><div v-if="!frozen"><button :disabled="busy || !unit.rawQuestionText.trim()" @click="emit('resolveQaUnit', unit.id, { action: 'CREATE_LIVE' })">新增为现场问答</button><button :disabled="busy" @click="emit('resolveQaUnit', unit.id, { action: 'IGNORE' })">忽略此组问答</button></div></article></section>
    </div>
  </aside>
</template>

<style scoped>
.record-review-panel { display:flex; flex-direction:column; min-width:0; min-height:0; height:100%; background:var(--surface); border-radius:13px; overflow:hidden; color:var(--ink-700); font-size:var(--text-base); }
.review-panel-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; padding:24px 24px 12px; }.review-panel-heading > div:first-child { display:flex; align-items:center; gap:14px; }.review-panel-heading h2 { margin:0; font-size:var(--text-xl); color:var(--ink-700); }.review-panel-heading span { background:var(--surface-sunken); color:var(--primary-600); padding:7px 12px; border-radius:20px; font-size:var(--text-sm); }
button,input,select,textarea { font:inherit; }button { min-height:44px; border:1px solid var(--line-300); border-radius:8px; padding:0 14px; background:var(--surface); color:var(--primary-600); cursor:pointer; font-size:var(--text-base); }button:disabled { opacity:.5; cursor:not-allowed; }button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible { outline:3px solid var(--ink-300); outline-offset:2px; }.review-sort { display:flex; gap:8px; }.review-sort button { border-radius:24px; min-height:38px; }.review-sort button.active,button.primary { background:var(--primary-600); border-color:var(--primary-600); color:var(--surface); }
.review-batch { display:flex; gap:10px; padding:0 24px; }.review-batch button { flex:1; }.review-instruction { margin:12px 24px; color:var(--ink-400); font-size:var(--text-sm); line-height:1.7; }.review-fragments { flex:1; min-height:0; overflow:auto; padding:0 24px 24px; }
.review-fragment { padding:18px; border:1px solid var(--primary-100); border-radius:10px; margin-bottom:12px; }.review-fragment.uncertain { border-color:var(--warning-600); background:var(--warning-100); }.review-fragment.confirmed { background:var(--success-100); }.review-fragment > header { display:flex; align-items:center; flex-wrap:wrap; gap:12px; color:var(--ink-400); font-size:var(--text-sm); }.fragment-select { display:flex; align-items:center; gap:8px; }input[type=checkbox] { width:20px; height:20px; accent-color:var(--primary-600); }.fragment-state { display:flex; align-items:center; gap:4px; margin-left:auto; padding:4px 9px; border-radius:20px; background:var(--primary-100); color:var(--ink-400); }.uncertain .fragment-state { color:var(--warning-600); background:var(--warning-100); }.confirmed .fragment-state { color:var(--success-700); background:var(--success-100); }
.fragment-confidence { margin:12px 0 6px; color:var(--ink-400); font-size:var(--text-sm); }.fragment-text { margin:0; font-size:var(--text-md); line-height:1.85; color:var(--ink-700); white-space:pre-wrap; overflow-wrap:anywhere; }.fragment-actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }.fragment-actions button:first-child { background:var(--primary-600); color:var(--surface); border-color:var(--primary-600); }
.fragment-revision { margin-top:14px; font-size:var(--text-sm); color:var(--ink-400); }.fragment-revision summary { display:flex; align-items:center; gap:6px; cursor:pointer; color:var(--ink-500); min-height:30px; }.fragment-revision p { line-height:1.8; overflow-wrap:anywhere; }.review-correction { display:grid; gap:10px; margin-top:12px; }.review-correction label { display:grid; gap:8px; }.review-correction input,.review-correction select,.review-correction textarea { min-width:0; min-height:44px; width:100%; border:1px solid var(--line-300); border-radius:7px; background:var(--surface); color:var(--ink-700); padding:8px; }.discard { color:var(--danger-700); }
.review-empty { display:grid; justify-items:center; gap:18px; padding:48px 12px; color:var(--ink-400); }.review-qa-units { border-top:1px solid var(--line-200); padding-top:20px; }.review-qa-units h3 { font-size:var(--text-lg); }.review-qa-units article { padding:16px; margin-top:12px; border:1px solid var(--warning-100); border-radius:10px; background:var(--warning-100); }.review-qa-units p { line-height:1.8; overflow-wrap:anywhere; }.review-qa-units article > div { display:flex; flex-wrap:wrap; gap:10px; }
@media(max-width:1100px) { .review-panel-heading { padding:20px 18px 12px; }.review-batch { padding:0 18px; }.review-instruction { margin:12px 18px; }.review-fragments { padding:0 18px 20px; } }
</style>
