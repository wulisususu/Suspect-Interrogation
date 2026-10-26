<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { createLongPress } from '../utils/longPress'

/** 长按按钮：指针或键盘（Enter / 空格）按住满时长才触发 confirm，按住期间显示进度。 */
const props = withDefaults(defineProps<{ durationMs?: number; disabled?: boolean }>(), { durationMs: 800, disabled: false })
const emit = defineEmits<{ confirm: [] }>()

const holding = ref(false)
const press = createLongPress(props.durationMs, () => {
  holding.value = false
  emit('confirm')
})

function begin() {
  if (props.disabled || holding.value) return
  holding.value = true
  press.start()
}
function end() {
  holding.value = false
  press.cancel()
}
function onKeydown(event: KeyboardEvent) {
  if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) {
    event.preventDefault()
    begin()
  }
}

onBeforeUnmount(end)
</script>

<template>
  <button
    type="button"
    class="long-press"
    :class="{ holding }"
    :disabled="disabled"
    :style="{ '--hold-ms': `${durationMs}ms` }"
    @pointerdown="begin"
    @pointerup="end"
    @pointerleave="end"
    @pointercancel="end"
    @keydown="onKeydown"
    @keyup="end"
    @blur="end"
  >
    <span class="long-press-fill" aria-hidden="true"></span>
    <span class="long-press-label"><slot /></span>
  </button>
</template>

<style scoped>
.long-press { position: relative; overflow: hidden; touch-action: none; user-select: none; }
.long-press-fill { position: absolute; inset: 0 100% 0 0; background: rgba(255, 255, 255, 0.24); }
.long-press.holding .long-press-fill { inset: 0; transition: inset var(--hold-ms) linear; }
.long-press-label { position: relative; }
</style>
