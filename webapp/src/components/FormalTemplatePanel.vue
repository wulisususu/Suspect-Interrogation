<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import type { CaseSummary, DocumentSignerRole, DocumentSigningState, FactItem, SessionState } from '../types/interrogation'
import type { CaseQuestionUpdateInput, FormalQuestion, FormalQuestionRound, QAUnitResolution } from '../types/templateInterrogation'
import { clearDrop, dropArmed, pendingDrop } from '../composables/pendingDrop'

const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  session: SessionState
  questions: FormalQuestion[]
  rounds: FormalQuestionRound[]
  busy: boolean
  documentFrozen: boolean
  documentLocked: boolean
  signingState: DocumentSigningState | null
  signingBusy: string
  captureRunning: boolean
  completionMode?: boolean
}>()

const emit = defineEmits<{
  updateQuestion: [questionId: string, input: CaseQuestionUpdateInput]
  reorder: [questionIds: string[]]
  removeQuestion: [questionId: string]
  updateAnswer: [targetId: string, answerText: string]
  attachFragmentAnswer: [questionId: string, fragmentIds: string[]]
  createLiveQuestionFromFragments: [fragmentIds: string[], afterQuestionId: string | null]
  saveLibrary: [questionId: string]
  insertPending: [pendingId: string, afterQuestionId: string | null]
  resolveQaUnit: [qaUnitId: string, resolution: QAUnitResolution]
  print: []
  freeze: []
  sign: [role: DocumentSignerRole]
  updateHeader: [target: 'case' | 'fact', key: string, value: string]
}>()

const questionDrafts = reactive<Record<string, string>>({})
const canonicalAnswerDrafts = reactive<Record<string, string>>({})
const draggingBodyId = ref('')
const dragOverKey = ref('')
const paper = ref<HTMLElement | null>(null)
const showMetadata = ref(false)
const orderedQuestions = computed(() => [...props.questions].sort((a, b) => a.sortOrder - b.sortOrder))
const openingQuestions = computed(() => orderedQuestions.value.filter((q) => q.sectionType === 'OPENING'))
const bodyQuestions = computed(() => orderedQuestions.value.filter((q) => q.sectionType === 'BODY'))
const closingQuestions = computed(() => orderedQuestions.value.filter((q) => q.sectionType === 'CLOSING'))
const lastOpeningId = computed(() => openingQuestions.value.at(-1)?.id ?? null)

watch(() => props.questions, async (items) => {
  for (const item of items) {
    questionDrafts[item.id] = item.text
    canonicalAnswerDrafts[item.id] = item.formalAnswerText ?? ''
  }
  await nextTick()
  resizeEditors()
}, { immediate: true, deep: true })
function resizeEditors() {
  paper.value?.querySelectorAll('textarea').forEach(input => {
    input.style.height = 'auto'
    input.style.height = `${input.scrollHeight}px`
  })
}
onMounted(resizeEditors)

function roundsFor(questionId: string) {
  return props.rounds.filter((r) => r.caseQuestionId === questionId && r.status !== 'DETACHED').sort((a, b) => a.roundNo - b.roundNo)
}
function latestRound(questionId: string) { return roundsFor(questionId).at(-1) }
function saveQuestion(question: FormalQuestion) {
  if (question.locked || props.documentFrozen || props.busy) return
  const text = (questionDrafts[question.id] || '').trim()
  if (text && text !== question.text.trim()) emit('updateQuestion', question.id, { text })
}
function saveCanonicalAnswer(question: FormalQuestion) {
  if (props.documentFrozen || props.busy) return
  const answer = (canonicalAnswerDrafts[question.id] || '').trim()
  if (answer !== (question.formalAnswerText ?? '').trim()) emit('updateAnswer', question.id, answer)
}
function signatureFor(role: DocumentSignerRole) { return props.signingState?.signatures.find((s) => s.signerRole === role) }
function formatSignedAt(value?: number) {
  return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) : ''
}
function formatRecordTime(value?: number | null) {
  if (!value) return '____年__月__日__时__分'
  const d = new Date(value)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}时${String(d.getMinutes()).padStart(2, '0')}分`
}
function factText(key: string, fallback = '') {
  const value = props.facts.find((item) => item.key === key)?.value?.trim()
  return !value || value === '未录入' ? fallback : value
}
function saveHeader(event: Event, target: 'case' | 'fact', key: string) {
  if (props.documentFrozen || props.busy) return
  const value = (event.target as HTMLInputElement).value.trim()
  emit('updateHeader', target, key, value)
}
function autoGrow(event: Event) {
  const input = event.target as HTMLTextAreaElement
  input.style.height = 'auto'
  input.style.height = `${input.scrollHeight}px`
}
function startBodyDrag(event: DragEvent, id: string) {
  if (props.documentFrozen || props.busy || !event.dataTransfer) return
  draggingBodyId.value = id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-formal-body-question', id)
}
function dropBody(event: DragEvent, targetId: string) {
  event.preventDefault()
  const sourceId = event.dataTransfer?.getData('application/x-formal-body-question') || draggingBodyId.value
  if (!sourceId || sourceId === targetId) return
  const ids = bodyQuestions.value.map((q) => q.id)
  const from = ids.indexOf(sourceId); const to = ids.indexOf(targetId)
  if (from < 0 || to < 0) return
  ids.splice(to, 0, ids.splice(from, 1)[0])
  emit('reorder', ids)
  draggingBodyId.value = ''; dragOverKey.value = ''
}
const QA_MIME = 'application/x-formal-qa-unit'
const FORMAL_ANSWER_FRAGMENT_MIME = 'application/x-formal-answer-fragments'
const transcriptFragmentArmed = computed(() => pendingDrop.value?.entries.some((entry) => entry.mime === FORMAL_ANSWER_FRAGMENT_MIME) ?? false)
type QaDragPayload = { qaUnitId: string; mode: 'QA' | 'ANSWER' }

function qaDragPayload(event: DragEvent): QaDragPayload | null {
  const raw = event.dataTransfer?.getData(QA_MIME)
  if (!raw) return null
  try {
    const payload = JSON.parse(raw) as Partial<QaDragPayload>
    if (!payload.qaUnitId || (payload.mode !== 'QA' && payload.mode !== 'ANSWER')) return null
    return payload as QaDragPayload
  } catch { return null }
}

function fragmentDragPayload(event: DragEvent): string[] {
  const raw = event.dataTransfer?.getData(FORMAL_ANSWER_FRAGMENT_MIME)
  if (!raw) return []
  try {
    const payload = JSON.parse(raw) as { fragmentIds?: unknown }
    return Array.isArray(payload.fragmentIds)
      ? payload.fragmentIds.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
      : []
  } catch { return [] }
}

function fragmentDragText(event: DragEvent): string {
  const raw = event.dataTransfer?.getData(FORMAL_ANSWER_FRAGMENT_MIME)
  if (!raw) return ''
  try {
    const payload = JSON.parse(raw) as { text?: unknown }
    return typeof payload.text === 'string' ? payload.text.trim() : ''
  } catch { return '' }
}

function allowPendingDrop(event: DragEvent, key: string) {
  const types = event.dataTransfer?.types ?? []
  if (!props.documentFrozen && (types.includes('application/x-formal-pending-question') || types.includes(QA_MIME) || types.includes(FORMAL_ANSWER_FRAGMENT_MIME))) {
    event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'; dragOverKey.value = key
  }
}

function dropQaCreateLive(event: DragEvent) {
  event.preventDefault(); dragOverKey.value = ''
  if (props.documentFrozen) return
  const payload = qaDragPayload(event)
  if (payload?.mode === 'QA') emit('resolveQaUnit', payload.qaUnitId, { action: 'CREATE_LIVE' })
}

function dropQaOnQuestion(event: DragEvent, questionId: string) {
  event.preventDefault(); dragOverKey.value = ''
  if (props.documentFrozen) return
  if (insertFragmentIntoQuestion(event, questionId)) return
  const payload = qaDragPayload(event)
  if (payload?.mode === 'QA') emit('resolveQaUnit', payload.qaUnitId, { action: 'LINK_QA', caseQuestionId: questionId })
}

function insertFragmentIntoQuestion(event: DragEvent, questionId: string, input?: HTMLTextAreaElement | null) {
  if (props.documentFrozen || props.busy) return false
  const question = props.questions.find((item) => item.id === questionId)
  const text = fragmentDragText(event)
  if (!question || question.locked || !text) return false
  const current = questionDrafts[questionId] ?? question.text
  const target = event.target instanceof HTMLTextAreaElement ? event.target : input
  const start = target?.selectionStart ?? current.length
  const end = target?.selectionEnd ?? current.length
  const updated = `${current.slice(0, start)}${text}${current.slice(end)}`
  questionDrafts[questionId] = updated
  emit('updateQuestion', questionId, { text: updated.trim() })
  return true
}

function dropAnswerOnQuestion(event: DragEvent, questionId: string) {
  event.preventDefault(); dragOverKey.value = ''
  if (props.documentFrozen) return
  const fragmentIds = fragmentDragPayload(event)
  if (fragmentIds.length) {
    emit('attachFragmentAnswer', questionId, fragmentIds)
    return
  }
  const payload = qaDragPayload(event)
  if (payload?.mode === 'ANSWER') emit('resolveQaUnit', payload.qaUnitId, { action: 'LINK_ANSWER', caseQuestionId: questionId })
}

function dropLiveQuestionFromFragments(event: DragEvent, afterQuestionId: string | null) {
  event.preventDefault(); dragOverKey.value = ''
  if (props.documentFrozen) return
  const fragmentIds = fragmentDragPayload(event)
  if (fragmentIds.length) emit('createLiveQuestionFromFragments', [fragmentIds[0]], afterQuestionId)
}

function dropGap(event: DragEvent, afterQuestionId: string | null) {
  if (event.dataTransfer?.types.includes(FORMAL_ANSWER_FRAGMENT_MIME)) {
    dropLiveQuestionFromFragments(event, afterQuestionId)
    return
  }
  if (event.dataTransfer?.types.includes(QA_MIME)) { dropQaCreateLive(event); return }
  dropPending(event, afterQuestionId)
}
/** 触摸屏不会产生 HTML5 拖放事件：点击投放目标时，若已有选中载荷，
 *  就合成一个 DragEvent 交给上面的 drop 处理函数复用，业务逻辑零改动。 */
function tapAnswerOnQuestion(questionId: string) {
  dropArmed((event) => dropAnswerOnQuestion(event, questionId))
}
function tapQaOnQuestionField(questionId: string, clickEvent: MouseEvent) {
  const input = clickEvent.target instanceof HTMLTextAreaElement ? clickEvent.target : null
  dropArmed((event) => {
    if (!insertFragmentIntoQuestion(event, questionId, input)) dropQaOnQuestion(event, questionId)
  })
}
function tapGap(afterQuestionId: string | null) {
  dropArmed((event) => dropGap(event, afterQuestionId))
}

function dropPending(event: DragEvent, afterQuestionId: string | null) {
  event.preventDefault(); dragOverKey.value = ''
  const raw = event.dataTransfer?.getData('application/x-formal-pending-question')
  if (!raw || props.documentFrozen) return
  try { const payload = JSON.parse(raw) as { pendingId?: string }; if (payload.pendingId) emit('insertPending', payload.pendingId, afterQuestionId) } catch { /* invalid external drag */ }
}
</script>

<template>
  <section class="formal-record-shell">
    <article ref="paper" class="formal-record-paper" :class="{ 'review-record-paper': completionMode }" aria-label="正式询问笔录编辑器">
      <div v-if="pendingDrop" role="status" style="position:sticky;top:0;z-index:6;display:flex;gap:12px;align-items:center;justify-content:space-between;margin:12px 16px 0;padding:9px 12px;border:1px solid #173b68;border-radius:8px;background:#e9f3ff;color:#173b68;font:13px system-ui,sans-serif">
        <span v-if="transcriptFragmentArmed">已选中一段转写——请点击正式笔录中的「问」或「答」栏录入</span>
        <span v-else>已选中「{{ pendingDrop.label }}」—— 请点击要放入的「问」或「答」栏位</span>
        <button type="button" style="border:1px solid #173b68;background:#fff;color:#173b68;border-radius:6px;padding:3px 10px;font:12px system-ui,sans-serif" @click="clearDrop()">取消</button>
      </div>
      <header class="record-paper-header">
        <div class="record-title-block"><h1>询问笔录</h1><span>第 1 次</span></div>
        <div v-if="!completionMode" class="record-top-actions record-no-print">
          <button :disabled="busy || signingBusy !== ''" @click="emit('print')">
            {{ documentFrozen ? '打印正式笔录' : '打印预览' }}
          </button>
          <button class="primary" :disabled="documentFrozen || signingBusy !== '' || captureRunning" @click="emit('freeze')">
            {{ signingBusy === 'freeze' ? '正在完成语音处理…' : documentFrozen ? '笔录已冻结' : '结束并冻结笔录' }}
          </button>
          <button :disabled="!signingState || !!signatureFor('SUSPECT') || signingBusy !== '' || documentLocked" @click="emit('sign', 'SUSPECT')">
            {{ signatureFor('SUSPECT') ? `被询问人已签 ${formatSignedAt(signatureFor('SUSPECT')?.signedAt)}` : '被询问人签名' }}
          </button>
          <button :disabled="!signingState || !!signatureFor('OFFICER') || signingBusy !== '' || documentLocked" @click="emit('sign', 'OFFICER')">
            {{ signatureFor('OFFICER') ? `民警已签 ${formatSignedAt(signatureFor('OFFICER')?.signedAt)}` : '民警签名' }}
          </button>
        </div>
      </header>

      <button v-if="completionMode" class="record-meta-toggle record-no-print" :aria-expanded="showMetadata" @click="showMetadata = !showMetadata">{{ showMetadata ? '收起身份与询问信息' : '展开身份与询问信息' }}</button>
      <section v-show="!completionMode || showMetadata" class="record-meta-grid">
        <p><b>时间</b><span>{{ formatRecordTime(session.startedAt || summary.createdAt) }} 至 {{ session.endedAt ? formatRecordTime(session.endedAt) : '____________' }}</span></p>
        <p><b>地点</b><input class="record-meta-editor" aria-label="地点" :value="factText('interrogation_place')" :disabled="busy || documentFrozen" placeholder="填写询问地点" @change="saveHeader($event, 'fact', 'interrogation_place')"></p>
        <p><b>询问人</b><input class="record-meta-editor short" aria-label="询问人" :value="summary.officerName === '当前警官' ? '' : summary.officerName" :disabled="busy || documentFrozen" placeholder="填写询问人" @change="saveHeader($event, 'case', 'officerName')"><span class="record-meta-label">工作单位</span><input class="record-meta-editor" aria-label="询问人工作单位" :value="factText('officer_unit')" :disabled="busy || documentFrozen" @change="saveHeader($event, 'fact', 'officer_unit')"></p>
        <p><b>记录人</b><input class="record-meta-editor short" aria-label="记录人" :value="factText('recorder_name')" :disabled="busy || documentFrozen" placeholder="填写记录人" @change="saveHeader($event, 'fact', 'recorder_name')"><span class="record-meta-label">工作单位</span><input class="record-meta-editor" aria-label="记录人工作单位" :value="factText('recorder_unit')" :disabled="busy || documentFrozen" @change="saveHeader($event, 'fact', 'recorder_unit')"></p>
        <p><b>被询问人</b><input class="record-meta-editor" aria-label="被询问人" :value="summary.suspectName === '待录入' ? '' : summary.suspectName" :disabled="busy || documentFrozen" placeholder="填写被询问人" @change="saveHeader($event, 'case', 'suspectName')"></p>
        <p><b>身份证证件种类及号码</b><input class="record-meta-editor short" aria-label="身份证件种类" :value="factText('id_document_type', '身份证')" :disabled="busy || documentFrozen" @change="saveHeader($event, 'fact', 'id_document_type')"><span class="record-meta-label">，</span><input class="record-meta-editor" aria-label="身份证件号码" :value="summary.idNumber" :disabled="busy || documentFrozen" @change="saveHeader($event, 'case', 'idNumber')"></p>
        <p><b>性别</b><input class="record-meta-editor tiny" aria-label="性别" :value="summary.gender" :disabled="busy || documentFrozen" @change="saveHeader($event, 'case', 'gender')"><span class="record-meta-label">出生日期</span><input class="record-meta-editor" aria-label="出生日期" :value="summary.birthDate" :disabled="busy || documentFrozen" @change="saveHeader($event, 'case', 'birthDate')"></p>
        <p><b>联系方式</b><input class="record-meta-editor" aria-label="联系方式" :value="factText('contact')" :disabled="busy || documentFrozen" @change="saveHeader($event, 'fact', 'contact')"></p>
        <p><b>现住址</b><input class="record-meta-editor" aria-label="现住址" :value="summary.address" :disabled="busy || documentFrozen" @change="saveHeader($event, 'case', 'address')"></p>
        <p><b>户籍所在地</b><input class="record-meta-editor" aria-label="户籍所在地" :value="factText('household_registration')" :disabled="busy || documentFrozen" @change="saveHeader($event, 'fact', 'household_registration')"></p>
      </section>

      <section class="record-qa-section fixed-opening">
        <div v-for="q in openingQuestions" :key="q.id" class="record-qa fixed-question">
          <p class="record-question"><b>问：</b><span>{{ q.text }}</span></p>
          <label class="record-answer qa-answer-drop" :class="{ 'record-answer-armed': transcriptFragmentArmed }" @dragover="allowPendingDrop($event, `answer-${q.id}`)" @dragleave="dragOverKey = ''" @drop.stop="dropAnswerOnQuestion($event, q.id)" @click="tapAnswerOnQuestion(q.id)"><b>答：</b><textarea v-model="canonicalAnswerDrafts[q.id]" :disabled="busy || documentFrozen" rows="1" @input="autoGrow($event)" @blur="saveCanonicalAnswer(q)"></textarea><small class="record-no-print">聊天记录或答案可拖到这里</small></label>
          <small v-if="latestRound(q.id)?.actualQuestionText && latestRound(q.id)?.actualQuestionText !== q.text" class="actual-question record-no-print">现场原问法：{{ latestRound(q.id)?.actualQuestionText }}</small>
        </div>
      </section>

      <div class="record-section-label record-no-print"><span>案件动态问答区</span><small>右侧实时对话可拖入；本区可拖动排序、编辑或移出</small></div>
      <div class="record-drop-zone record-no-print" :class="{ active: dragOverKey === 'body-start' }" @dragover="allowPendingDrop($event, 'body-start')" @dragleave="dragOverKey = ''" @drop="dropGap($event, lastOpeningId)">拖到这里插入为第一条案件问题 / 民警提问 / 整组问答</div>

      <section class="record-qa-section body-section">
        <article v-for="q in bodyQuestions" :key="q.id" class="record-qa body-question" draggable="true" @dragstart="startBodyDrag($event, q.id)" @dragover.prevent @drop="dropBody($event, q.id)">
          <div class="body-question-tools record-no-print"><span class="drag-handle" title="拖动排序">⋮⋮</span><span>{{ q.source === 'LIVE' ? '实时对话' : q.source === 'STANDARD' ? '问题库' : '本案问题' }}</span><button :disabled="busy || documentFrozen" @click="emit('saveLibrary', q.id)">存入题库</button><button class="danger-link" :disabled="busy || documentFrozen" @click="emit('removeQuestion', q.id)">移出笔录</button></div>
          <label class="record-question editable-question qa-question-drop" :class="{ 'record-question-armed': transcriptFragmentArmed }" @dragover="allowPendingDrop($event, `qa-${q.id}`)" @drop.stop="dropQaOnQuestion($event, q.id)" @click="tapQaOnQuestionField(q.id, $event)"><b>问：</b><textarea v-model="questionDrafts[q.id]" :disabled="busy || documentFrozen" rows="1" @input="autoGrow($event)" @blur="saveQuestion(q)"></textarea><small class="record-no-print">整组 QA 可拖到本题</small></label>
          <label class="record-answer qa-answer-drop" :class="{ 'record-answer-armed': transcriptFragmentArmed }" @dragover="allowPendingDrop($event, `answer-${q.id}`)" @dragleave="dragOverKey = ''" @drop.stop="dropAnswerOnQuestion($event, q.id)" @click="tapAnswerOnQuestion(q.id)"><b>答：</b><textarea v-model="canonicalAnswerDrafts[q.id]" :disabled="busy || documentFrozen" rows="2" placeholder="等待现场回答" @input="autoGrow($event)" @blur="saveCanonicalAnswer(q)"></textarea><small class="record-no-print">聊天记录或答案可拖到这里</small></label>
          <small v-if="latestRound(q.id)?.actualQuestionText && latestRound(q.id)?.actualQuestionText !== q.text" class="actual-question record-no-print">现场原问法：{{ latestRound(q.id)?.actualQuestionText }}</small>
          <div class="record-drop-zone compact record-no-print" :class="{ active: dragOverKey === q.id }" @dragover="allowPendingDrop($event, q.id)" @dragleave="dragOverKey = ''" @drop="dropGap($event, q.id)">拖到这里，插入在本题之后 / 民警提问新建现场问题</div>
        </article>
        <div v-if="!bodyQuestions.length" class="record-body-empty record-no-print">案件动态问答区暂为空。将右侧民警提问拖到这里，或从问题准备区加入。</div>
      </section>

      <section class="record-qa-section fixed-closing">
        <div v-for="q in closingQuestions" :key="q.id" class="record-qa fixed-question">
          <p class="record-question"><b>问：</b><span>{{ q.text }}</span></p>
          <label class="record-answer qa-answer-drop" :class="{ 'record-answer-armed': transcriptFragmentArmed }" @dragover="allowPendingDrop($event, `answer-${q.id}`)" @dragleave="dragOverKey = ''" @drop.stop="dropAnswerOnQuestion($event, q.id)" @click="tapAnswerOnQuestion(q.id)"><b>答：</b><textarea v-model="canonicalAnswerDrafts[q.id]" :disabled="busy || documentFrozen" rows="1" @input="autoGrow($event)" @blur="saveCanonicalAnswer(q)"></textarea><small class="record-no-print">聊天记录或答案可拖到这里</small></label>
          <small v-if="latestRound(q.id)?.actualQuestionText && latestRound(q.id)?.actualQuestionText !== q.text" class="actual-question record-no-print">现场原问法：{{ latestRound(q.id)?.actualQuestionText }}</small>
        </div>
      </section>

      <footer class="record-integrity-footer">
        <span v-if="signingState">冻结版本 {{ signingState.version }} · 完整性{{ signingState.integrityValid ? '已校验' : '异常' }}</span>
        <span v-else>正式问题 {{ orderedQuestions.length }} · 问答轮次 {{ rounds.filter((r) => r.status !== 'DETACHED').length }}</span>
      </footer>
    </article>
  </section>
</template>

<style scoped>
.qa-question-drop, .qa-answer-drop { position: relative; border-radius: 6px; }
.qa-question-drop.record-question-armed { outline: 2px solid #2874e5; background: #f2f7ff; cursor: pointer; }
.qa-answer-drop.record-answer-armed { outline: 2px solid #2874e5; background: #f2f7ff; cursor: pointer; }
.qa-question-drop:has(textarea:focus):not(.record-question-armed), .qa-answer-drop:has(textarea:focus):not(.record-answer-armed) { outline: none; }
.qa-question-drop > small, .qa-answer-drop > small { margin-left: 8px; color: #84909d; font-size: 10px; }
</style>
