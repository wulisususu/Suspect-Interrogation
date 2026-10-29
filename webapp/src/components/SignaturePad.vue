<script setup lang="ts">
/**
 * 手写签名画板（管理员预录入用）。
 *
 * 与 ⑤ 签署页里的文末热区画布是两套场景：这里只负责“画 + 导出 PNG”，
 * 不参与文书的冻结/签署流程，避免动到证据链代码。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { cssToken } from '../utils/cssToken'

const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false })
const emit = defineEmits<{ changed: [hasInk: boolean] }>()

const canvas = ref<HTMLCanvasElement | null>(null)
const hasInk = ref(false)
const strokes = ref(0)
let drawing = false
let last: { x: number; y: number; p: number } | null = null

function prepare() {
  const element = canvas.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  const ratio = Math.max(1, window.devicePixelRatio || 1)
  element.width = Math.max(1, Math.round(rect.width * ratio))
  element.height = Math.max(1, Math.round(rect.height * ratio))
  const context = element.getContext('2d')
  if (!context) return
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, rect.width, rect.height)
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.strokeStyle = cssToken('--paper-ink', '#242b35')
}

function point(event: PointerEvent) {
  const rect = canvas.value?.getBoundingClientRect()
  return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0), p: event.pressure || 0.5 }
}

function start(event: PointerEvent) {
  if (props.disabled) return
  const element = canvas.value
  if (!element) return
  element.setPointerCapture(event.pointerId)
  drawing = true
  last = point(event)
  strokes.value += 1
}

function move(event: PointerEvent) {
  if (!drawing || props.disabled) return
  const context = canvas.value?.getContext('2d')
  const next = point(event)
  if (!context || !last) return
  context.lineWidth = 1.7 + Math.min(1, next.p) * 1.8
  context.beginPath()
  context.moveTo(last.x, last.y)
  context.lineTo(next.x, next.y)
  context.stroke()
  last = next
  if (!hasInk.value) {
    hasInk.value = true
    emit('changed', true)
  }
}

function end(event: PointerEvent) {
  const element = canvas.value
  if (element?.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId)
  drawing = false
  last = null
}

function clear() {
  strokes.value = 0
  hasInk.value = false
  emit('changed', false)
  prepare()
}

function toDataUrl(): string | null {
  const element = canvas.value
  if (!element || !hasInk.value) return null
  return element.toDataURL('image/png')
}

onMounted(() => {
  prepare()
  window.addEventListener('resize', prepare)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', prepare)
})

defineExpose({ clear, toDataUrl })
</script>

<template>
  <div class="signature-pad">
    <canvas
      ref="canvas"
      :class="{ disabled }"
      aria-label="手写签名区域"
      @pointerdown.prevent="start"
      @pointermove.prevent="move"
      @pointerup="end"
      @pointercancel="end"
      @pointerleave="end"
    />
    <div class="pad-actions">
      <span class="hint">{{ hasInk ? '已落笔，可保存' : '请在框内手写签名' }}</span>
      <button type="button" class="ghost" :disabled="!hasInk" @click="clear">清除重写</button>
    </div>
  </div>
</template>

<style scoped>
.signature-pad { display: flex; flex-direction: column; gap: var(--space-2); }
.signature-pad canvas { width: 100%; height: 200px; border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); touch-action: none; cursor: crosshair; }
.signature-pad canvas.disabled { opacity: 0.6; cursor: not-allowed; }
.pad-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.hint { color: var(--ink-500); font-size: var(--text-xs); }
.ghost { min-height: 32px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-700); font-size: var(--text-xs); cursor: pointer; }
.ghost:disabled { opacity: 0.5; cursor: default; }
</style>
