<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, AudioLines, Mic, Square } from '@lucide/vue'
import { answerStats, circled, type SelfQuestion } from '../utils/selfService'

/**
 * 自助模式 · ③自助问答（样板「自助式模式 · 民警在场」）
 *
 * 一屏一题：本人点「开始回答」直接说，说完点「说完了」，文字转成待摘入草稿挂在本题上；
 * 本人勾选「本题确认无误」只是留痕，正本仍由在场民警核对后摘入。跳过的题如实记为未获取。
 */
const props = defineProps<{
  questions: SelfQuestion[]
  current: number
  recording: boolean
  /** 正在开始 / 结束录音或转写中 */
  busy: boolean
  liveText: string
  elapsedMs: number
  confirmedIds: string[]
  officerLabel: string
  templateTitle: string
  /** 设备或身份未就绪时不能录音，给出原因 */
  blockedReason: string
}>()

const emit = defineEmits<{
  select: [index: number]
  start: []
  stop: []
  redo: []
  skip: []
  next: []
  confirm: [questionId: string, value: boolean]
  finish: []
}>()

const question = computed(() => props.questions[props.current] ?? null)
const stats = computed(() => answerStats(props.questions))
const elementCount = computed(() => new Set(props.questions.map((item) => item.elementKey).filter(Boolean)).size)
const confirmed = computed(() => Boolean(question.value && props.confirmedIds.includes(question.value.id)))
const answered = computed(() => props.questions.map((item, index) => ({ ...item, index })).filter((item) => item.answer))
const timer = computed(() => {
  const seconds = Math.floor(Math.max(0, props.elapsedMs) / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
})
const heard = computed(() => {
  const text = question.value?.answer || ''
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
})
const previewAnswer = computed(() => (props.recording ? props.liveText : question.value?.answer) || '')

function short(text: string, size: number) {
  return text.length > size ? `${text.slice(0, size)}…` : text
}
function dotState(item: SelfQuestion, index: number) {
  if (index === props.current) return 'current'
  return item.answer ? 'done' : 'todo'
}
</script>

<template>
  <section v-if="question" class="ss-answer">
    <header class="ss-progress">
      <strong>第 {{ current + 1 }} 题 / 共 {{ questions.length }} 题</strong>
      <span>《{{ templateTitle || '本案' }}》模板<template v-if="elementCount"> · 核心要素 {{ elementCount }} 项</template></span>
      <ol class="ss-dots" aria-label="题目进度">
        <li v-for="(item, index) in questions" :key="item.id">
          <button
            type="button"
            :class="`is-${dotState(item, index)}`"
            :aria-current="index === current ? 'step' : undefined"
            :aria-label="`第 ${index + 1} 题${item.answer ? '，已回答' : ''}`"
            :disabled="recording || busy"
            @click="emit('select', index)"
          >{{ index + 1 }}</button>
        </li>
      </ol>
    </header>

    <div class="ss-answer-grid">
      <article class="ss-question-card" aria-live="polite">
        <div class="ss-question-meta">
          <span>问题 {{ current + 1 }}<template v-if="question.elementLabel"><i aria-hidden="true">·</i>核心要素 {{ circled(question.elementOrdinal) }} {{ question.elementLabel }}</template></span>
          <span v-if="recording" class="ss-pill is-live"><i aria-hidden="true"></i>正在录音</span>
          <span v-else-if="question.answer" class="ss-pill is-done">已回答</span>
          <span v-else class="ss-pill">待回答</span>
        </div>
        <h1>{{ question.text }}</h1>
        <p class="ss-instruction">请按你自己的话回答，说完点一下「说完了」。答错了也没关系，之后可以修改。</p>

        <div class="ss-transcript" :class="{ 'is-live': recording }">
          <div v-if="recording" class="ss-transcript-head">
            <span class="ss-timer">{{ timer }}</span>
            <AudioLines :size="28" class="ss-wave" aria-hidden="true" />
            <small>请靠近话筒说话</small>
          </div>
          <p v-if="recording" class="ss-transcript-text">{{ liveText || '正在听，请直接说…' }}</p>
          <p v-else-if="busy" class="ss-transcript-text is-muted">正在把您说的话转成文字…</p>
          <template v-else-if="question.answer">
            <small class="ss-transcript-label">已记下的回答</small>
            <p class="ss-transcript-text">{{ question.answer }}</p>
          </template>
          <p v-else class="ss-transcript-text is-muted">点下方「开始回答」后直接说话，文字会自动出现在这里。</p>
        </div>

        <div v-if="!recording && !busy && question.answer && !confirmed" class="ss-heard" role="status">
          <span>我们听到的是「{{ heard }}」，对吗？</span>
          <div>
            <button type="button" @click="emit('confirm', question.id, true)">是</button>
            <button type="button" @click="emit('redo')">不对，改一下</button>
          </div>
        </div>
        <p v-if="blockedReason && !recording" class="ss-blocked" role="alert">{{ blockedReason }}</p>

        <footer class="ss-question-actions">
          <template v-if="recording">
            <button type="button" class="ss-primary" :disabled="busy" @click="emit('stop')"><Square :size="16" fill="currentColor" aria-hidden="true" />说完了 · 结束录音</button>
            <button type="button" class="ss-secondary" :disabled="busy" @click="emit('redo')">重新说一遍</button>
          </template>
          <template v-else-if="question.answer">
            <button type="button" class="ss-secondary" :disabled="busy || !!blockedReason" @click="emit('redo')">重新说一遍</button>
            <button type="button" class="ss-primary" :disabled="busy" @click="emit('next')">下一题<ArrowRight :size="18" aria-hidden="true" /></button>
          </template>
          <button v-else type="button" class="ss-primary" :disabled="busy || !!blockedReason" @click="emit('start')"><Mic :size="18" aria-hidden="true" />{{ busy ? '请稍候…' : '开始回答' }}</button>
          <button v-if="!question.answer || !recording" type="button" class="ss-skip" :disabled="recording || busy" @click="emit('skip')">跳过本题</button>
        </footer>
      </article>

      <aside class="ss-side">
        <section class="ss-side-card">
          <h2>怎么用这台机器</h2>
          <ol class="ss-howto">
            <li><b>1</b>屏幕会念一遍问题，照着回答就行</li>
            <li><b>2</b>说完点「说完了」，文字会自动出现</li>
            <li><b>3</b>说错了可以点「重新说一遍」</li>
            <li><b>4</b>全部答完，由在场民警核对并签字</li>
          </ol>
        </section>

        <section class="ss-side-card">
          <h2>已经记下 {{ stats.answered }} 题</h2>
          <ul v-if="answered.length" class="ss-answered">
            <li v-for="item in answered" :key="item.id">
              <button type="button" :disabled="recording || busy" @click="emit('select', item.index)">
                <span>{{ circled(item.index + 1) }} {{ short(item.text, 12) }}</span><i aria-hidden="true">·</i><em>{{ short(item.answer, 10) }}</em>
              </button>
            </li>
          </ul>
          <p v-else class="ss-side-muted">还没有记下的回答</p>
          <small class="ss-side-muted">已录 {{ stats.chars }} 字<i aria-hidden="true">·</i>未答 {{ stats.unanswered }} 题</small>
        </section>

        <section class="ss-side-card ss-mine">
          <h2>我的确认</h2>
          <p class="ss-officer"><i aria-hidden="true"></i>{{ officerLabel || '在场民警' }} 全程在场</p>
          <label class="ss-check">
            <input
              type="checkbox"
              :checked="confirmed"
              :disabled="!question.answer || recording || busy"
              @change="emit('confirm', question.id, ($event.target as HTMLInputElement).checked)"
            />
            <span>我说的没错，本题确认无误</span>
          </label>
          <small>勾选表示你听清并认可本题记录；最终仍由在场民警核对后写入笔录</small>
        </section>

        <section class="ss-side-card">
          <h2>答完后，笔录会是这样</h2>
          <p class="ss-paper">问：{{ question.text }}</p>
          <p class="ss-paper">答：{{ previewAnswer || '（未获取）' }}</p>
          <small class="ss-side-muted">文字会先转成初稿，由在场民警核对后定稿；你答过的每一句都会保留。</small>
        </section>

        <div class="ss-finish">
          <small v-if="stats.unanswered">未答的 {{ stats.unanswered }} 题将标记为「未获取」，民警可在笔录中补充</small>
          <button type="button" class="ss-primary" :disabled="recording || busy" @click="emit('finish')">结束并交民警定稿</button>
        </div>
      </aside>
    </div>
  </section>
  <section v-else class="ss-answer ss-empty">
    <p>本案模板没有需要本人回答的问题，请交由民警继续办理。</p>
    <button type="button" class="ss-primary" @click="emit('finish')">交民警定稿</button>
  </section>
</template>

<style scoped>
.ss-answer { display: flex; flex-direction: column; height: 100%; background: var(--surface-sunken); }
.ss-progress { display: flex; align-items: center; gap: var(--space-6); padding: var(--space-3) var(--space-8); border-bottom: 1px solid var(--line-200); background: var(--surface); }
.ss-progress strong { color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.ss-progress > span { color: var(--ink-500); font-size: var(--text-sm); }
.ss-dots { display: flex; gap: var(--space-3); margin: 0 0 0 auto; padding: 0; list-style: none; }
.ss-dots button { width: 36px; height: 36px; border: 0; border-radius: 50%; background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-sm); font-weight: 600; }
.ss-dots button.is-done { background: var(--success-700); color: var(--surface); }
.ss-dots button.is-current { background: var(--navy-800); color: var(--surface); box-shadow: var(--shadow-focus); }
.ss-dots button:disabled { opacity: 1; cursor: default; }

.ss-answer-grid { display: grid; flex: 1 1 auto; grid-template-columns: minmax(0, 1fr) 440px; gap: var(--space-6); min-height: 0; padding: var(--space-5) var(--space-8); }
.ss-question-card { display: flex; flex-direction: column; gap: var(--space-4); min-height: 0; padding: var(--space-6) var(--space-8); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-card); }
.ss-question-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); color: var(--ink-500); font-size: var(--text-sm); }
.ss-question-meta i { margin: 0 var(--space-3); font-style: normal; }
.ss-pill { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-1) var(--space-3); border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-sm); font-weight: 600; }
.ss-pill.is-live { background: var(--danger-100); color: var(--danger-700); }
.ss-pill.is-live i { width: 10px; height: 10px; border-radius: 50%; background: var(--danger-600); animation: ss-blink 1.2s ease-in-out infinite; }
.ss-pill.is-done { background: var(--success-100); color: var(--success-700); }
.ss-question-card h1 { margin: 0; color: var(--ink-900); font-size: var(--text-display); font-weight: 650; line-height: 1.3; }
.ss-instruction { margin: 0; color: var(--ink-500); font-size: var(--text-md); }

.ss-transcript { display: flex; flex-direction: column; gap: var(--space-3); flex: 1 1 auto; min-height: 160px; padding: var(--space-6); border-radius: var(--radius-md); background: var(--surface-sunken); overflow: auto; }
.ss-transcript-head { display: flex; align-items: center; gap: var(--space-3); }
.ss-transcript-head small { margin-left: auto; color: var(--ink-400); font-size: var(--text-xs); }
.ss-timer { color: var(--danger-600); font-size: var(--text-3xl); font-weight: 600; font-variant-numeric: tabular-nums; }
.ss-wave { color: var(--danger-600); }
.ss-transcript-label { color: var(--ink-400); font-size: var(--text-xs); }
.ss-transcript-text { margin: 0; color: var(--ink-900); font-size: var(--text-xl); line-height: 1.7; white-space: pre-wrap; }
.ss-transcript-text.is-muted { color: var(--ink-400); font-size: var(--text-md); }

.ss-heard { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-3) var(--space-5); border-radius: var(--radius-md); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-md); font-weight: 600; }
.ss-heard div { display: flex; gap: var(--space-3); flex: none; }
.ss-heard button { min-height: 48px; padding: 0 var(--space-6); border: 1px solid var(--primary-600); border-radius: var(--radius-md); background: var(--surface); color: var(--primary-600); font-size: var(--text-md); font-weight: 600; }
.ss-blocked { margin: 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--danger-100); color: var(--danger-700); font-size: var(--text-sm); }

.ss-question-actions { display: flex; align-items: center; gap: var(--space-3); }
.ss-primary, .ss-secondary { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); min-height: 58px; padding: 0 var(--space-7); border-radius: var(--radius-md); font-size: var(--text-lg); font-weight: 600; }
.ss-primary { border: 0; background: var(--primary-600); color: var(--surface); box-shadow: var(--shadow-active); }
.ss-primary:hover:not(:disabled) { background: var(--primary-700); }
.ss-primary:disabled, .ss-secondary:disabled { opacity: 0.5; box-shadow: none; cursor: default; }
.ss-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); font-weight: 500; }
.ss-skip { margin-left: auto; min-height: 44px; padding: 0; border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-md); }
.ss-skip:disabled { opacity: 0.4; cursor: default; }

.ss-side { display: flex; flex-direction: column; gap: var(--space-3); min-height: 0; overflow: auto; }
.ss-side-card { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-4) var(--space-5); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); }
.ss-side-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 650; }
.ss-howto { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; color: var(--ink-700); font-size: var(--text-sm); }
.ss-howto li { display: flex; align-items: center; gap: var(--space-3); }
.ss-howto b { display: grid; place-items: center; flex: none; width: 24px; height: 24px; border-radius: 50%; background: var(--primary-50); color: var(--primary-600); font-size: var(--text-xs); }
.ss-answered { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.ss-answered button { display: flex; align-items: center; gap: var(--space-2); width: 100%; min-height: 32px; padding: 0; border: 0; background: transparent; color: var(--ink-500); font-size: var(--text-sm); text-align: left; }
.ss-answered button:hover:not(:disabled) { color: var(--primary-600); }
.ss-answered em { color: var(--ink-700); font-style: normal; }
.ss-answered i, .ss-side-muted i { margin: 0 var(--space-2); font-style: normal; }
.ss-side-muted { margin: 0; color: var(--ink-400); font-size: var(--text-xs); }
.ss-mine { border-color: var(--success-600); background: var(--success-100); }
.ss-mine h2 { color: var(--success-700); }
.ss-officer { display: flex; align-items: center; gap: var(--space-2); margin: 0; color: var(--success-700); font-size: var(--text-sm); font-weight: 600; }
.ss-officer i { width: 8px; height: 8px; border-radius: 50%; background: var(--success-700); }
.ss-mine small { color: var(--success-700); font-size: var(--text-xs); }
.ss-check { display: inline-flex; align-items: center; gap: var(--space-3); color: var(--ink-900); font-size: var(--text-md); cursor: pointer; }
.ss-check input { width: 24px; height: 24px; accent-color: var(--success-700); }
.ss-paper { margin: 0; color: var(--ink-700); font-size: var(--text-sm); line-height: 1.6; }
.ss-finish { display: flex; flex-direction: column; gap: var(--space-2); margin-top: auto; }
.ss-finish small { color: var(--ink-500); font-size: var(--text-xs); }
.ss-finish .ss-primary { width: 100%; }

.ss-empty { align-items: center; justify-content: center; gap: var(--space-4); color: var(--ink-700); font-size: var(--text-lg); }

@keyframes ss-blink { 50% { opacity: 0.35; } }

@media (max-width: 1280px) {
  .ss-answer { height: auto; min-height: 100%; }
  .ss-answer-grid { grid-template-columns: 1fr; }
  .ss-progress { flex-wrap: wrap; }
}
</style>
