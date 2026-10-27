<script setup lang="ts">
import { computed, unref, type Ref } from 'vue'
import type { VoiceprintAudioSource } from '../api/browserVoiceprint'
import { audioInputMode } from '../config/audioInput'

const props = defineProps<{
  source: VoiceprintAudioSource | null | Ref<VoiceprintAudioSource | null>
  reason: string | Ref<string>
  secureContext: boolean | Ref<boolean>
  compact?: boolean
}>()

const sourceValue = computed(() => unref(props.source))
const effectiveSource = computed<VoiceprintAudioSource>(() => sourceValue.value ?? audioInputMode)
const reasonValue = computed(() => {
  if (sourceValue.value) return unref(props.reason)
  return effectiveSource.value === 'BROWSER'
    ? '局域网测试模式：固定使用当前 Windows 浏览器麦克风；失败会直接提示，不回退 Linux 麦克风。'
    : '生产模式：固定使用 Linux 一体机 ALSA 麦克风，不请求浏览器权限。'
})
const secureContextValue = computed(() => unref(props.secureContext))
</script>

<template>
  <aside class="voiceprint-source-banner" :class="[effectiveSource.toLowerCase(), { compact }]" aria-live="polite">
    <details v-if="compact" class="compact-source-details">
      <summary>
        <strong v-if="effectiveSource === 'BROWSER'">Windows 浏览器麦克风</strong>
        <strong v-else>Linux 一体机麦克风</strong>
        <span v-if="effectiveSource === 'BROWSER'" class="security-chip" :class="{ secure: secureContextValue }">{{ secureContextValue ? '可用' : '需授权' }}</span>
        <span v-else class="security-chip secure">可用</span>
      </summary>
      <p>{{ reasonValue }}</p>
    </details>
    <div v-if="!compact">
      <strong v-if="effectiveSource === 'BROWSER'">音源：Windows 浏览器麦克风（局域网测试）</strong>
      <strong v-else>音源：Linux 一体机麦克风（生产）</strong>
      <span>{{ reasonValue }}</span>
    </div>
    <template v-if="!compact">
      <span v-if="effectiveSource === 'BROWSER'" class="security-chip" :class="{ secure: secureContextValue }">{{ secureContextValue ? '浏览器麦克风上下文可用' : '需用 LAN 测试启动脚本' }}</span>
      <span v-else class="security-chip secure">ALSA 本机音源</span>
    </template>
  </aside>
</template>

<style scoped>
.voiceprint-source-banner { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:10px 18px; border-bottom:1px solid var(--line-300); background:var(--surface-sunken); color:var(--ink-700); }
.voiceprint-source-banner > div { display:flex; flex-direction:column; gap:3px; min-width:0; }
.voiceprint-source-banner strong { font-size:var(--text-base); }
.voiceprint-source-banner span { font-size:var(--text-xs); color:var(--ink-500); }
.voiceprint-source-banner.browser { background:var(--success-100); border-bottom-color:var(--success-100); }
.voiceprint-source-banner.alsa { background:var(--warning-100); border-bottom-color:var(--warning-600); }
.security-chip { flex:none; border:1px solid var(--warning-600); border-radius:999px; padding:5px 9px; background:var(--surface); color:var(--warning-700) !important; font-weight:700; }
.security-chip.secure { border-color:var(--success-100); color:var(--success-700) !important; }
.compact-source-details { min-width:0; }
.compact-source-details summary { display:flex; align-items:center; justify-content:flex-end; gap:6px; cursor:pointer; list-style:none; white-space:nowrap; }
.compact-source-details summary::-webkit-details-marker { display:none; }
.compact-source-details strong { font-size:var(--text-xs); }
.compact-source-details .security-chip { padding:2px 6px; font-size:var(--text-xs); }
.compact-source-details p { max-width:300px; margin:5px 0 0; color:var(--ink-500); font-size:var(--text-xs); line-height:1.4; white-space:normal; }
.voiceprint-source-banner.compact { justify-content:flex-end; padding:3px 6px; border:1px solid var(--line-300); border-radius:6px; }
</style>
