<script setup lang="ts">
import { computed, ref } from 'vue'
import { backendErrorMessage, fetchRuntimeCapabilities } from '../api/interrogation'
import type { RuntimeCapabilities, RuntimeCapability } from '../runtime'

const open = ref(false)
const loading = ref(false)
const error = ref('')
const capabilities = ref<RuntimeCapabilities | null>(null)
const entries = computed(() => capabilities.value
  ? Object.values(capabilities.value).filter((item) => ['asr', 'ocr', 'llm', 'recording'].includes(item.name))
  : [])
const llmCapability = computed(() => capabilities.value?.llm)
const triggerText = computed(() => {
  if (!llmCapability.value) return 'AI：状态未读取'
  if (llmCapability.value.state === 'AVAILABLE') return 'AI：本地 Runtime 可用'
  if (llmCapability.value.state === 'MODEL_NOT_INSTALLED') return 'AI：模型未安装'
  return 'AI：本地 Runtime 未就绪'
})
const triggerTitle = computed(() => llmCapability.value?.reason || `本地 AI Runtime 状态：${llmCapability.value?.state || '尚未读取'}`)

function stateText(item: RuntimeCapability) { return item.state === 'AVAILABLE' ? '可用' : item.reason || item.state }
async function load(force = false) {
  loading.value = true; error.value = ''
  try { capabilities.value = await fetchRuntimeCapabilities(force) }
  catch (cause) { error.value = backendErrorMessage(cause) }
  finally { loading.value = false }
}
async function show() { open.value = true; await load() }
</script>

<template>
  <button class="ai-settings-trigger" :title="triggerTitle" @click="show">{{ triggerText }}</button>
  <div v-if="open" class="runtime-mask" @click.self="open = false">
    <section class="runtime-panel">
      <header><div><h2>本地 AI Runtime</h2><p>仅显示 RK3588 当前已部署的离线能力。</p></div><button @click="open = false">关闭</button></header>
      <div class="runtime-toolbar"><span>不提供浏览器内模型扫描、导入、切换或旧控制台测试。</span><button :disabled="loading" @click="load(true)">{{ loading ? '刷新中…' : '刷新状态' }}</button></div>
      <p v-if="error" class="runtime-error">{{ error }}</p>
      <div v-else-if="loading && !capabilities" class="runtime-empty">正在读取 Runtime 状态…</div>
      <div v-else class="runtime-list"><article v-for="item in entries" :key="item.name" :class="{ available: item.state === 'AVAILABLE' }"><strong>{{ item.name.toUpperCase() }}</strong><span>{{ stateText(item) }}</span></article></div>
    </section>
  </div>
</template>

<style scoped>
.ai-settings-trigger { border: 1px solid var(--ink-500); border-radius: 8px; background: var(--navy-900); color: var(--primary-100); padding: 7px 11px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-mask { position: fixed; inset: 0; z-index: 1300; display: grid; place-items: center; padding: 22px; background: rgba(10, 24, 38, .58); }.runtime-panel { width: min(660px, 96vw); border-radius: 16px; overflow: hidden; background: var(--surface-sunken); box-shadow: 0 26px 76px rgba(6, 20, 33, .28); }.runtime-panel header, .runtime-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 18px 22px; background: var(--surface); border-bottom: 1px solid var(--primary-100); }.runtime-panel h2 { margin: 0; color: var(--navy-900); font-size: 20px; }.runtime-panel p { margin: 6px 0 0; color: var(--ink-500); font-size: 13px; }button { border: 1px solid var(--line-300); border-radius: 8px; background: var(--surface); color: var(--ink-700); padding: 8px 12px; }.runtime-toolbar { padding: 12px 22px; color: var(--ink-500); font-size: 13px; }.runtime-list { display: grid; gap: 10px; padding: 18px 22px 24px; }.runtime-list article { display: flex; justify-content: space-between; gap: 16px; padding: 12px 14px; border: 1px solid var(--line-300); border-radius: 9px; color: var(--warning-700); background: var(--warning-100); }.runtime-list article.available { color: var(--success-700); background: var(--success-100); }.runtime-error, .runtime-empty { margin: 18px 22px 24px; padding: 12px; border-radius: 8px; background: var(--danger-100); color: var(--danger-600); }.runtime-empty { background: var(--surface-sunken); color: var(--ink-500); }
</style>
