<script setup lang="ts">
import { cssToken } from '../utils/cssToken'
import { onMounted, onUnmounted, ref, watch } from 'vue'

import type { AudioLevelSample } from '../types/interrogation'

const props = withDefaults(defineProps<{
  samples: AudioLevelSample[]
  barWidth?: number
  barGap?: number
  cornerRadius?: number
  maxHeight?: number
  minHeight?: number
  sampleLimit?: number
  smoothing?: number
}>(), {
  barWidth: 2,
  barGap: 2,
  cornerRadius: 1,
  maxHeight: 42,
  minHeight: 2,
  sampleLimit: 240,
  smoothing: 0.35,
})

const canvas = ref<HTMLCanvasElement | null>(null)
const waveform: number[] = []
let lastSampleCount: number | null = null
let lastSampleRate: number | null = null
let frame = 0

function appendSample(sample: AudioLevelSample) {
  const peak = Number.isFinite(sample.peak) ? Math.max(0, sample.peak) : 0
  const rms = Number.isFinite(sample.rms) ? Math.max(0, sample.rms) : 0
  const normalized = Math.min(1, Math.max(rms, peak * 0.72) / 32768)
  const target = Math.min(1, Math.sqrt(normalized) * 1.25)
  const previous = waveform.at(-1) ?? target
  const alpha = Math.min(1, Math.max(0, props.smoothing))
  const smoothed = previous + (target - previous) * alpha
  waveform.push(Math.max(0.035, Math.min(1, smoothed)))
  if (waveform.length > props.sampleLimit) waveform.splice(0, waveform.length - props.sampleLimit)
  lastSampleCount = sample.sampleCount
  lastSampleRate = sample.sampleRate
}

watch(() => props.samples, (samples) => {
  if (!samples.length) return
  let lastIndex = -1
  if (lastSampleCount !== null) {
    for (let index = samples.length - 1; index >= 0; index -= 1) {
      const sample = samples[index]!
      if (sample.sampleCount === lastSampleCount && sample.sampleRate === lastSampleRate) {
        lastIndex = index
        break
      }
    }
  }

  if (lastSampleCount !== null && lastIndex < 0) {
    const newest = samples[samples.length - 1]!
    if (newest.sampleRate !== lastSampleRate || newest.sampleCount < lastSampleCount) {
      waveform.length = 0
      lastSampleCount = null
      lastSampleRate = null
    }
  }

  let startIndex = lastSampleCount === null ? 0 : lastIndex + 1
  if (lastSampleCount !== null && lastIndex < 0) {
    startIndex = samples.findIndex((sample) => sample.sampleRate === lastSampleRate && sample.sampleCount > lastSampleCount!)
    if (startIndex < 0) return
  }
  for (const sample of samples.slice(startIndex)) appendSample(sample)
}, { immediate: true, flush: 'post' })

function draw() {
  const element = canvas.value
  const context = element?.getContext('2d')
  if (!element || !context) return

  const bounds = element.getBoundingClientRect()
  const width = bounds.width
  const height = bounds.height
  if (!width || !height) return
  const dpr = Math.max(1, window.devicePixelRatio || 1)
  const pixelWidth = Math.round(width * dpr)
  const pixelHeight = Math.round(height * dpr)
  if (element.width !== pixelWidth || element.height !== pixelHeight) {
    element.width = pixelWidth
    element.height = pixelHeight
  }

  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, width, height)
  const center = height / 2
  context.beginPath()
  context.moveTo(0, center + 0.5)
  context.lineTo(width, center + 0.5)
  context.strokeStyle = cssToken('--line-300', '#d6dfeb')
  context.lineWidth = 1
  context.stroke()

  const step = Math.max(1, props.barWidth + props.barGap)
  const visibleCount = Math.min(props.sampleLimit, waveform.length, Math.ceil(width / step))
  const visible = waveform.slice(-visibleCount)
  const maxBarHeight = Math.min(props.maxHeight, Math.max(2, height - 4))
  const minBarHeight = Math.min(props.minHeight, maxBarHeight)
  context.fillStyle = cssToken('--ink-500', '#5b6b83')
  for (let index = 0; index < visible.length; index += 1) {
    const amplitude = visible[index] ?? 0
    const barHeight = minBarHeight + amplitude * (maxBarHeight - minBarHeight)
    const x = width - props.barWidth - 2 - (visible.length - index - 1) * step
    if (x + props.barWidth < 0 || x > width) continue
    const y = center - barHeight / 2
    const radius = Math.min(props.cornerRadius, props.barWidth / 2, barHeight / 2)
    context.beginPath()
    context.roundRect(x, y, props.barWidth, barHeight, radius)
    context.fill()
  }
}

function animate() {
  draw()
  frame = window.requestAnimationFrame(animate)
}

onMounted(() => {
  frame = window.requestAnimationFrame(animate)
})

onUnmounted(() => {
  window.cancelAnimationFrame(frame)
})
</script>

<template>
  <canvas ref="canvas" class="recorder-waveform-canvas" aria-hidden="true"></canvas>
</template>

<style scoped>
.recorder-waveform-canvas {
  display: block;
  width: 100%;
  height: 48px;
}
</style>
