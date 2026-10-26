<script setup lang="ts">
// 触屏软键盘:点击输入框自动弹出、失焦自动收起;中文拼音(离线词典)+ 英文/数字直输
// 仅在触屏设备(coarse pointer / maxTouchPoints>0)自动启用,远程桌面浏览器不受影响
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  createSyllableSet,
  loadPinyinDict,
  lookupCandidates,
  type PinyinDict,
} from '../utils/pinyinIme'

const EDITABLE_SELECTOR = [
  'input:not([readonly]):not([disabled]):not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"]):not([type="file"]):not([type="range"])',
  'textarea:not([readonly]):not([disabled])',
  '[contenteditable="true"]',
  '[contenteditable=""]',
].join(', ')

const LETTER_ROWS = [
  ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
  ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
  ['z', 'x', 'c', 'v', 'b', 'n', 'm'],
]
const DIGIT_ROWS = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['@', '#', '¥', '%', '&', '*', '-', '+', '(', ')'],
  [':', ';', ',', '.', '?', '!', "'", '"', '/'],
]

const visible = ref(false)
const page = ref<'abc' | '123'>('abc')
const shiftOn = ref(false)
const cnMode = ref(true)
const buffer = ref('')
const dictReady = ref(false)
const keyboardElement = ref<HTMLElement | null>(null)
let keyboardSizeObserver: ResizeObserver | null = null

let dict: PinyinDict | null = null
let syllables: Set<string> | null = null
let target: HTMLElement | null = null
let hideTimer: ReturnType<typeof setTimeout> | null = null

const candidates = computed(() => {
  if (!cnMode.value || !buffer.value || !dict) return { words: [], chars: [], all: [] }
  return lookupCandidates(dict, buffer.value)
})

const firstCandidate = computed(() => candidates.value.all[0] ?? '')
const showCandidateBar = computed(() => cnMode.value && buffer.value.length > 0)
const spaceLabel = computed(() => (showCandidateBar.value && firstCandidate.value ? firstCandidate.value : '空格'))

function updateKeyboardSpace() {
  const height = visible.value ? keyboardElement.value?.getBoundingClientRect().height || 0 : 0
  document.documentElement.style.setProperty('--osk-height', height + 'px')
  if (height) target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

watch([visible, showCandidateBar], async () => {
  await nextTick()
  keyboardSizeObserver?.disconnect()
  if (keyboardElement.value && typeof ResizeObserver !== 'undefined') {
    keyboardSizeObserver = new ResizeObserver(updateKeyboardSpace)
    keyboardSizeObserver.observe(keyboardElement.value)
  }
  updateKeyboardSpace()
})

function isTouchDevice(): boolean {
  return (typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches)
    || navigator.maxTouchPoints > 0
}

function isEditable(el: Element | null): el is HTMLElement {
  return el instanceof HTMLElement && el.matches(EDITABLE_SELECTOR)
}

function onfocusin(event: FocusEvent) {
  if (!isTouchDevice() || !isEditable(event.target as Element | null)) return
  target = event.target as HTMLElement
  if (hideTimer) { clearTimeout(hideTimer); hideTimer = null }
  visible.value = true
  void ensureDict()
  window.setTimeout(() => {
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, 60)
}

function onfocusout() {
  if (!visible.value) return
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = setTimeout(() => {
    hideTimer = null
    if (!isEditable(document.activeElement)) {
      visible.value = false
      resetComposition()
      target = null
    }
  }, 10)
}

async function ensureDict() {
  if (dictReady.value) return
  try {
    dict = await loadPinyinDict()
    syllables = createSyllableSet(dict)
    dictReady.value = true
  } catch (error) {
    console.warn('[osk] pinyin dict load failed, fallback to direct input', error)
  }
}

function resetComposition() {
  buffer.value = ''
  page.value = 'abc'
  shiftOn.value = false
}

function fallbackInsert(el: HTMLElement, text: string) {
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? el.value.length
    el.value = el.value.slice(0, start) + text + el.value.slice(end)
    const caret = start + text.length
    el.setSelectionRange(caret, caret)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  } else {
    el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, data: text, inputType: 'insertText' }))
    const node = document.createTextNode(text)
    const selection = window.getSelection()
    if (selection && selection.rangeCount) {
      const range = selection.getRangeAt(0)
      range.deleteContents()
      range.insertNode(node)
      range.setStartAfter(node)
      range.collapse(true)
      selection.removeAllRanges()
      selection.addRange(range)
    } else {
      el.appendChild(node)
    }
    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }))
  }
}

function fallbackBackspace(el: HTMLElement) {
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? el.value.length
    if (start === end && start > 0) {
      el.value = el.value.slice(0, start - 1) + el.value.slice(end)
      el.setSelectionRange(start - 1, start - 1)
    } else {
      el.value = el.value.slice(0, start) + el.value.slice(end)
      el.setSelectionRange(start, start)
    }
    el.dispatchEvent(new Event('input', { bubbles: true }))
  }
}

function insertText(text: string) {
  if (!target) return
  if (document.activeElement !== target) target.focus()
  let ok = false
  try {
    ok = document.execCommand('insertText', false, text)
  } catch {
    ok = false
  }
  if (!ok) fallbackInsert(target, text)
}

function deleteChar() {
  if (!target) return
  let ok = false
  try {
    ok = document.execCommand('delete')
  } catch {
    ok = false
  }
  if (!ok) fallbackBackspace(target)
}

function pressLetter(key: string) {
  if (cnMode.value) {
    buffer.value += key
    return
  }
  const text = shiftOn.value ? key.toUpperCase() : key
  shiftOn.value = false
  insertText(text)
}

function pressSymbol(key: string) {
  insertText(key)
}

function onSpace() {
  if (showCandidateBar.value && firstCandidate.value) {
    insertText(firstCandidate.value)
    buffer.value = ''
    return
  }
  insertText(' ')
}

function onEnter() {
  if (showCandidateBar.value) {
    insertText(buffer.value)
    buffer.value = ''
    return
  }
  if (target instanceof HTMLTextAreaElement) insertText('\n')
  else dismiss()
}

function onBackspace() {
  if (cnMode.value && buffer.value) {
    buffer.value = buffer.value.slice(0, -1)
    return
  }
  deleteChar()
}

function toggleCnMode() {
  cnMode.value = !cnMode.value
  buffer.value = ''
}

function toggleShift() {
  shiftOn.value = !shiftOn.value
}

function switchPage(next: 'abc' | '123') {
  page.value = next
}

function dismiss() {
  visible.value = false
  resetComposition()
}

function displayKey(key: string): string {
  if (cnMode.value || page.value === '123') return key
  return shiftOn.value ? key.toUpperCase() : key
}

onMounted(() => {
  document.addEventListener('focusin', onfocusin, true)
  document.addEventListener('focusout', onfocusout, true)
})

onBeforeUnmount(() => {
  keyboardSizeObserver?.disconnect()
  document.documentElement.style.removeProperty('--osk-height')
  document.removeEventListener('focusin', onfocusin, true)
  document.removeEventListener('focusout', onfocusout, true)
  if (hideTimer) clearTimeout(hideTimer)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" ref="keyboardElement" class="osk-root" aria-label="屏幕键盘" @pointerdown.stop>
      <div v-if="showCandidateBar" class="osk-candidate-bar">
        <span class="osk-buffer">{{ buffer }}</span>
        <div class="osk-candidate-list">
          <button
            v-for="(item, index) in candidates.all.slice(0, 12)"
            :key="`${item}-${index}`"
            type="button"
            class="osk-candidate"
            :class="{ 'osk-candidate-first': index === 0 }"
            @pointerdown.prevent
            @click="insertText(item); buffer = ''"
          >{{ item }}</button>
          <span v-if="!dictReady" class="osk-dict-hint">词典加载中…</span>
        </div>
      </div>

      <template v-if="page === 'abc'">
        <div v-for="(row, rowIndex) in LETTER_ROWS" :key="`l-${rowIndex}`" class="osk-row">
          <button
            v-if="rowIndex === 2"
            type="button"
            class="osk-key osk-key-fn"
            :class="{ 'osk-key-active': shiftOn }"
            @pointerdown.prevent
            @click="toggleShift"
          >⇧</button>
          <button
            v-for="key in row"
            :key="key"
            type="button"
            class="osk-key"
            @pointerdown.prevent
            @click="pressLetter(key)"
          >{{ displayKey(key) }}</button>
          <button
            v-if="rowIndex === 2"
            type="button"
            class="osk-key osk-key-fn"
            @pointerdown.prevent
            @click="onBackspace"
          >⌫</button>
        </div>
      </template>

      <template v-else>
        <div v-for="(row, rowIndex) in DIGIT_ROWS" :key="`d-${rowIndex}`" class="osk-row">
          <button
            v-for="key in row"
            :key="key"
            type="button"
            class="osk-key"
            @pointerdown.prevent
            @click="pressSymbol(key)"
          >{{ key }}</button>
          <button
            v-if="rowIndex === 2"
            type="button"
            class="osk-key osk-key-fn"
            @pointerdown.prevent
            @click="onBackspace"
          >⌫</button>
        </div>
      </template>

      <div class="osk-row">
        <button
          type="button"
          class="osk-key osk-key-fn osk-key-cn"
          :class="{ 'osk-key-active': cnMode }"
          @pointerdown.prevent
          @click="toggleCnMode"
        >{{ cnMode ? '中' : '英' }}</button>
        <button
          type="button"
          class="osk-key osk-key-fn"
          @pointerdown.prevent
          @click="switchPage(page === 'abc' ? '123' : 'abc')"
        >{{ page === 'abc' ? '123' : 'abc' }}</button>
        <button
          type="button"
          class="osk-key osk-key-fn"
          @pointerdown.prevent
          @click="pressSymbol('，')"
        >，</button>
        <button
          type="button"
          class="osk-key osk-key-space"
          @pointerdown.prevent
          @click="onSpace"
        >{{ spaceLabel }}</button>
        <button
          type="button"
          class="osk-key osk-key-fn"
          @pointerdown.prevent
          @click="pressSymbol('。')"
        >。</button>
        <button
          type="button"
          class="osk-key osk-key-fn osk-key-enter"
          @pointerdown.prevent
          @click="onEnter"
        >确认</button>
        <button
          type="button"
          class="osk-key osk-key-fn"
          aria-label="收起键盘"
          @pointerdown.prevent
          @click="dismiss"
        >▼</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.osk-root {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 2147483000;
  display: grid;
  gap: 6px;
  padding: 8px 8px calc(10px + env(safe-area-inset-bottom, 0px));
  background: var(--primary-100);
  border-top: 1px solid var(--primary-200);
  box-shadow: 0 -4px 16px rgba(32, 56, 77, 0.18);
  user-select: none;
  -webkit-user-select: none;
}
.osk-row { display: flex; gap: 6px; justify-content: center; }
.osk-key {
  flex: 1 1 0;
  min-width: 0;
  min-height: 54px;
  border: 1px solid var(--primary-200);
  border-radius: 8px;
  background: var(--surface);
  color: var(--navy-900);
  font-size: 20px;
  font-weight: 600;
  box-shadow: 0 1px 0 rgba(120, 145, 165, 0.8);
  touch-action: manipulation;
  padding: 0;
}
.osk-key:active { background: var(--primary-100); }
.osk-key-fn { flex: 1.3 1 0; background: var(--primary-100); font-size: 17px; }
.osk-key-active { background: var(--primary-600); color: var(--surface); border-color: var(--primary-600); }
.osk-key-space { flex: 4 1 0; }
.osk-key-enter { flex: 1.6 1 0; }
.osk-candidate-bar { display: flex; align-items: center; gap: 8px; min-height: 52px; }
.osk-buffer {
  flex: 0 0 auto;
  min-width: 56px;
  text-align: center;
  font-size: 18px;
  font-weight: 700;
  color: var(--primary-600);
  background: var(--surface);
  border: 1px dashed var(--ink-300);
  border-radius: 8px;
  padding: 10px 12px;
}
.osk-candidate-list {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  flex: 1 1 auto;
  scrollbar-width: thin;
}
.osk-candidate {
  flex: 0 0 auto;
  min-width: 56px;
  min-height: 46px;
  border: 1px solid var(--primary-200);
  border-radius: 8px;
  background: var(--surface);
  color: var(--navy-900);
  font-size: 19px;
  padding: 4px 10px;
  touch-action: manipulation;
}
.osk-candidate-first { background: var(--primary-600); color: var(--surface); border-color: var(--primary-600); }
.osk-dict-hint { color: var(--ink-500); font-size: 13px; white-space: nowrap; }
@media (max-height: 560px) {
  .osk-key { min-height: 44px; font-size: 17px; }
  .osk-candidate-bar { min-height: 44px; }
}
</style>
