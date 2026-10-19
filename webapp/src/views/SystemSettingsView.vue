<script setup lang="ts">
import { ref } from 'vue'
import OfficerVoiceprintLibrary from '../components/OfficerVoiceprintLibrary.vue'
import SpeakerCalibrationCenter from '../components/SpeakerCalibrationCenter.vue'

defineEmits<{ back: [] }>()

const activeTab = ref<'library' | 'calibration'>('library')
</script>

<template>
  <main class="system-settings-view">
    <header class="settings-topbar">
      <div>
        <button class="back-button" @click="$emit('back')">‹ 返回案件管理</button>
        <h1>嫌疑人询问系统</h1>
        <p>声纹登记与设备管理 · ERes2Net-large</p>
      </div>
    </header>

    <nav class="settings-tabs" aria-label="声纹系统设置">
      <button :class="{ active: activeTab === 'library' }" @click="activeTab = 'library'">民警声纹库</button>
      <button :class="{ active: activeTab === 'calibration' }" @click="activeTab = 'calibration'">设备校准中心</button>
    </nav>

    <OfficerVoiceprintLibrary v-if="activeTab === 'library'" />
    <SpeakerCalibrationCenter v-else />
  </main>
</template>

<style scoped>
.system-settings-view { height:100vh; overflow:auto; box-sizing:border-box; padding:0 32px 32px; background:#f4f6fb; font-size:15px; }
.settings-topbar,.runtime-header { padding:18px 20px; border:1px solid #c7d5e0; border-radius:10px; background:#fff; color:#20384d; }
.settings-topbar { margin:0 -32px 0; padding:14px 24px; border:0; border-radius:0; background:#19365d; color:#fff; }
.settings-topbar > div { display:flex; align-items:center; gap:20px; }
.settings-topbar span,.settings-topbar p,.runtime-header p,.runtime-note,.backend-health-grid small { color:#607588; }
.settings-topbar h1,.runtime-header h2 { margin:0; }
.settings-topbar h1 { font-size:20px; }.settings-topbar p { color:#a7b9d0; margin:0; font-size:14px; }
.back-button { width:max-content; min-height:40px; border:1px solid #7188a5; border-radius:7px; padding:0 14px; background:transparent; color:#fff; font:inherit; font-size:14px; cursor:pointer; }
.settings-tabs { display:flex; gap:8px; margin:0 -32px 28px; padding:0 32px; border-bottom:1px solid #dce5f1; background:#fff; }
.settings-tabs button { min-height:48px; border:0; border-bottom:3px solid transparent; padding:0 18px; background:transparent; color:#74859d; font:inherit; font-size:14px; cursor:pointer; }
.settings-tabs button.active { border-bottom-color:#327be8; background:#edf4ff; color:#205293; font-weight:600; }
.back-button:focus-visible,.settings-tabs button:focus-visible { outline:3px solid #87afe1; outline-offset:2px; }
.runtime-panel { display:grid; gap:14px; }
.runtime-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.runtime-header button { min-height:40px; border:1px solid #2476c9; border-radius:6px; padding:0 14px; background:#2476c9; color:#fff; font-weight:700; }
.runtime-header button:disabled { opacity:.5; }
.mode-grid,.backend-health-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.mode-grid { grid-template-columns:repeat(3,minmax(160px,1fr)); }
.mode-grid label,.backend-health-grid article { padding:14px; border:1px solid #c7d5e0; border-radius:8px; background:#fff; }
.authority-row { display:grid; grid-template-columns:auto minmax(180px,260px) 1fr; align-items:center; gap:12px; padding:14px; border:1px solid #b9cde0; border-radius:8px; background:#f8fbfe; }
.authority-row select { min-height:38px; border:1px solid #9fb2c3; border-radius:6px; padding:0 10px; background:#fff; }
.authority-row span { color:#607588; font-size:13px; }
.backend-health-grid article { display:grid; gap:7px; }
.backend-title { display:flex; justify-content:space-between; gap:12px; }
.backend-title span { border-radius:999px; padding:3px 8px; font-size:11px; font-weight:800; }
.backend-title .ready { background:#edf8f1; color:#267647; }
.backend-title .unavailable { background:#fff1ef; color:#a23b31; }
.backend-health-grid code { overflow-wrap:anywhere; color:#48667e; font-size:12px; }
.degraded-warning,.runtime-error { margin:0; padding:10px 12px; border:1px solid #e0b35f; border-radius:7px; background:#fff8e7; color:#875a0b; }
.runtime-loading { color:#607588; }
.runtime-note { margin:0; font-size:12px; }
@media (max-width:900px) { .mode-grid,.backend-health-grid,.authority-row { grid-template-columns:1fr; } .runtime-header { flex-direction:column; } }
@media(max-width:720px) { .system-settings-view { padding:0 16px 24px; }.settings-topbar { margin:0 -16px; padding:12px 16px; }.settings-topbar > div { flex-wrap:wrap; gap:12px; }.settings-topbar p { display:none; }.settings-tabs { margin:0 -16px 20px; padding:0 16px; } }
</style>
