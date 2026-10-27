<script setup lang="ts">
import { Play } from '@lucide/vue'

/** 录音播放器外观（样板 P32）：进度、倍速、时间戳跳转。录音回放尚未接入，控件全部禁用。 */
</script>

<template>
  <div class="player-shell" aria-label="录音播放器（功能待接入）">
    <button type="button" class="player-play" aria-label="播放" disabled><Play :size="16" /></button>
    <span class="player-track" aria-hidden="true"><span></span></span>
    <span class="player-time">00:00 / 00:00</span>
    <button type="button" class="player-speed" disabled title="倍速">倍速 1.0×</button>
  </div>
</template>

<style scoped>
.player-shell { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--surface-sunken); }
.player-play { display: grid; place-items: center; width: 36px; height: 36px; border: 0; border-radius: 50%; background: var(--primary-600); color: var(--surface); }
.player-track { position: relative; flex: 1; height: 6px; border-radius: var(--radius-pill); background: var(--line-200); }
.player-time { color: var(--ink-500); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.player-speed { min-height: 32px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface); color: var(--ink-500); font-size: var(--text-xs); }
</style>
