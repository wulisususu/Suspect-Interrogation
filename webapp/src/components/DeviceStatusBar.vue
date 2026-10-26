<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { backendErrorMessage, fetchRuntimeCapabilities, invokeDeviceAction } from '../api/interrogation'
import type { RuntimeCapabilities, RuntimeCapabilityName, RuntimeCapabilityState } from '../runtime'

const message = ref('')
const pending = ref('')
const capabilities = ref<RuntimeCapabilities | null>(null)

const items: Array<{ name: RuntimeCapabilityName; label: string }> = [
  { name: 'identity', label: '身份证读卡器' },
  { name: 'camera', label: '摄像头' },
  { name: 'microphone', label: '麦克风' },
  { name: 'signature', label: '签名板' },
  { name: 'asr', label: 'ASR' },
  { name: 'ocr', label: 'OCR' },
  { name: 'llm', label: 'LLM' },
]

const stateText: Record<RuntimeCapabilityState, string> = {
  AVAILABLE: '可用',
  NOT_CONNECTED: '未连接',
  NOT_CONFIGURED: '未配置',
  MODEL_NOT_INSTALLED: '模型未安装',
  BUSY: '忙碌',
  ERROR: '异常',
}

const capabilityItems = computed(() => items.map((item) => ({
  ...item,
  capability: capabilities.value?.[item.name],
})))

async function refresh(force = false) {
  capabilities.value = await fetchRuntimeCapabilities(force)
}

function available(name: RuntimeCapabilityName) {
  return capabilities.value?.[name]?.state === 'AVAILABLE'
}

async function invoke(type: 'fingerprint' | 'signature') {
  pending.value = type
  message.value = ''
  try {
    const result = await invokeDeviceAction(type)
    message.value = result.message || (result.success ? '设备操作完成' : '设备操作未完成')
    await refresh(true)
  } catch (error) {
    message.value = backendErrorMessage(error)
  } finally {
    pending.value = ''
  }
}

onMounted(() => {
  void refresh().catch((error) => { message.value = backendErrorMessage(error) })
})
</script>

<template>
  <div class="device-status-wrap">
    <div class="capability-strip" aria-label="Linux 本地能力状态">
      <span
        v-for="item in capabilityItems"
        :key="item.name"
        class="capability-chip"
        :class="(item.capability?.state || 'NOT_CONNECTED').toLowerCase()"
        :title="item.capability?.reason || stateText[item.capability?.state || 'NOT_CONNECTED']"
      >
        {{ item.label }} · {{ stateText[item.capability?.state || 'NOT_CONNECTED'] }}
      </span>
    </div>
    <div class="device-actions">
      <button class="device-button" :disabled="!!pending || !available('fingerprint')" @click="invoke('fingerprint')">
        {{ pending === 'fingerprint' ? '采集中…' : '指纹' }}
      </button>
      <button class="device-button" :disabled="!!pending || !available('signature')" @click="invoke('signature')">
        {{ pending === 'signature' ? '签字中…' : '签名' }}
      </button>
      <button class="device-button compact" :disabled="!!pending" @click="refresh(true)">刷新</button>
      <span v-if="message" class="device-message">{{ message }}</span>
    </div>
  </div>
</template>

<style scoped>
.device-status-wrap { display: flex; align-items: center; gap: 8px; min-width: 0; }
.capability-strip { display: flex; gap: 4px; max-width: 520px; overflow-x: auto; scrollbar-width: thin; }
.capability-chip { flex: 0 0 auto; border-radius: 999px; padding: 3px 6px; background: var(--canvas); color: var(--ink-500); font-size: var(--text-xs); white-space: nowrap; }
.capability-chip.available { background: var(--success-100); color: var(--success-700); }
.capability-chip.not_connected, .capability-chip.not_configured, .capability-chip.model_not_installed { background: var(--warning-100); color: var(--warning-600); }
.capability-chip.busy { background: var(--surface-sunken); color: var(--ink-500); }
.capability-chip.error { background: var(--danger-100); color: var(--danger-600); }
.device-actions { display: flex; align-items: center; gap: 5px; }
.device-button { border: 1px solid var(--ink-500); border-radius: 7px; background: var(--navy-900); color: var(--primary-100); padding: 6px 9px; font-size: var(--text-xs); }
.device-button.compact { padding-inline: 7px; }
.device-button:disabled { opacity: .45; cursor: not-allowed; }
.device-message { max-width: 180px; overflow: hidden; color: var(--line-300); font-size: var(--text-xs); text-overflow: ellipsis; white-space: nowrap; }
</style>
