<script setup lang="ts">
import { computed } from 'vue'
import VoiceprintEnrollmentGate from './VoiceprintEnrollmentGate.vue'
import type { CaseSummary, FactItem, OfficerVoiceprint, VoiceprintEnrollmentState, VoiceprintReadiness } from '../types/interrogation'

const props = defineProps<{
  suspectName: string
  readiness: VoiceprintReadiness
  officers: OfficerVoiceprint[]
  selectedInterrogatorOfficerId: string | null
  selectedRecorderOfficerId: string | null
  enrollmentState: VoiceprintEnrollmentState
  busy: boolean
  summary?: CaseSummary
  facts?: FactItem[]
  recorderName?: string
}>()

defineEmits<{
  suspectStart: []
  suspectStop: []
  selectInterrogator: [officerId: string | null]
  selectRecorder: [officerId: string | null]
  bindRoles: []
  back: []
}>()
const maskedId = computed(() => {
  const value = props.summary?.idNumber || ''
  return value.length > 8 ? value.slice(0, 4) + '*'.repeat(value.length - 8) + value.slice(-4) : value || '未填写'
})
const caseType = computed(() => {
  const fact = props.facts?.find((item) => item.key === 'case_type')?.value
  return (fact && fact !== '未录入' ? fact : props.summary?.caseType !== 'suspect_interrogation' ? props.summary?.caseType : '') || '未填写'
})
</script>

<template>
  <section class="voiceprint-setup-page">
    <div class="voiceprint-setup-main">
      <header class="voiceprint-setup-header"><h1>嫌疑人声纹采集</h1><p>{{ summary?.id || '当前案件' }} · {{ suspectName || '姓名待录入' }} · 主审民警 {{ summary?.officerName || '未指定' }} · 记录员 {{ recorderName || '未指定' }}</p></header>
      <nav class="capture-breadcrumb" aria-label="声纹采集流程"><button :disabled="busy || enrollmentState.phase === 'RECORDING' || enrollmentState.phase === 'PROCESSING'" @click="$emit('back')">准备检查单</button><span aria-hidden="true">/</span><strong>嫌疑人声纹采集 · 当前</strong><span>完成注册后返回检查单</span></nav>
    <VoiceprintEnrollmentGate
      :suspect-name="suspectName"
      :readiness="readiness"
      :officers="officers"
      :selected-interrogator-officer-id="selectedInterrogatorOfficerId"
      :selected-recorder-officer-id="selectedRecorderOfficerId"
      :enrollment-state="enrollmentState"
      :busy="busy"
      @suspect-start="$emit('suspectStart')"
      @suspect-stop="$emit('suspectStop')"
      @select-interrogator="$emit('selectInterrogator', $event)"
      @select-recorder="$emit('selectRecorder', $event)"
      @bind-roles="$emit('bindRoles')"
    >
      <template #guide><section class="reading-guide"><header><h2>朗读指引</h2><span>大字号 · 供采集时认读</span></header><div class="reading-text"><p>请以自然、连续的语速朗读以下内容：</p><blockquote>“早晨的阳光透过窗户，照亮了房间。街道两旁的树木随风轻轻摇动，远处传来人们交谈的声音。”<br />“说话时保持正常音量，按照自己的节奏读完句子，中途可以自然停顿和换气。”</blockquote></div><p class="reading-note">仅作朗读参考，也可自然交谈累计有效语音；无需刻意变声。</p></section></template>
      <template #return><button class="return-to-preparation" :disabled="busy || enrollmentState.phase === 'RECORDING' || enrollmentState.phase === 'PROCESSING'" @click="$emit('back')">返回准备检查单</button></template>
    </VoiceprintEnrollmentGate>
    </div>
    <aside class="capture-sidebar">
      <section><h2>身份确认</h2><dl><div><dt>姓名</dt><dd>{{ suspectName || '未填写' }}</dd></div><div><dt>证件号码</dt><dd>{{ maskedId }}</dd></div><div><dt>案件类型</dt><dd>{{ caseType }}</dd></div><div><dt>采集对象</dt><dd>嫌疑人本人</dd></div><div><dt>询问人 · 记录人</dt><dd>{{ summary?.officerName || '未指定' }} · {{ recorderName || '未指定' }}</dd></div></dl></section>
      <section><h2>采集要求</h2><ul><li>静音与长时间停顿不计入有效时长</li><li>避免多人同时讲话，以免影响声纹质量</li><li>保持正常音量与语速，无需刻意变声</li></ul></section>
      <section><h2>完成标准</h2><ol><li>有效语音累计达到目标时长后自动进行注册</li><li>以注册结果为准，注册成功后准备检查项更新</li><li>返回检查单，确认各项就绪后开始审讯</li></ol><p class="purpose-note">声纹用于本案的说话人识别</p></section>
      <section><h2>民警声纹绑定</h2><p>民警声纹为可选项。可在本页下方选择已登记的民警档案，保存本次角色选择。</p></section>
    </aside>
  </section>
</template>

<style scoped>
.voiceprint-setup-page { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:26px; min-height:100%; padding:28px 32px 32px; max-width:1920px; margin:0 auto; background:#f4f6fb; color:#243550; font-size:15px; }
.voiceprint-setup-main { display:grid; align-content:start; gap:18px; min-width:0; }
.voiceprint-setup-header h1 { margin:0 0 12px; font-size:26px; color:#1c2e49; }.voiceprint-setup-header p { margin:0; color:#748196; font-size:14px; line-height:1.8; }
.capture-breadcrumb { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:14px 18px; background:#e4ecf9; border-radius:9px; color:#7c8ea9; font-size:14px; }.capture-breadcrumb strong { color:#3263a1; font-weight:600; }.capture-breadcrumb button { background:transparent; border:0; padding:4px 0; font:inherit; color:#3263a1; cursor:pointer; }
.reading-guide { padding:22px 24px; border-radius:13px; background:#fff; }.reading-guide header { display:flex; flex-wrap:wrap; align-items:center; gap:14px; margin-bottom:14px; }.reading-guide h2,.capture-sidebar h2 { margin:0; font-size:18px; color:#26364c; }.reading-guide header span { padding:6px 12px; border-radius:20px; background:#edf3fc; color:#537eaf; font-size:13px; }
.reading-text { padding:18px 22px; background:#edf3fc; border-radius:9px; }.reading-text p { margin:0 0 12px; color:#7d8fa7; font-size:15px; }.reading-text blockquote { margin:0; color:#2e3d52; font-size:22px; font-weight:600; line-height:1.9; }.reading-note { margin:12px 0 0; color:#8796ac; font-size:13px; line-height:1.8; }
.return-to-preparation { min-height:48px; padding:0 20px; border:1px solid #ccd8e9; border-radius:9px; background:#fff; color:#205293; font:inherit; font-size:15px; cursor:pointer; }
button:disabled { opacity:.5; cursor:not-allowed; }button:focus-visible { outline:3px solid #87afe1; outline-offset:3px; }
.capture-sidebar { display:grid; align-content:start; gap:20px; }.capture-sidebar section { padding:24px; border-radius:13px; background:#fff; }.capture-sidebar h2 { margin-bottom:16px; font-size:16px; }.capture-sidebar dl { margin:0; }.capture-sidebar dl > div { display:grid; grid-template-columns:95px minmax(0,1fr); gap:10px; padding:9px 0; font-size:13px; }.capture-sidebar dt { color:#91a0b5; }.capture-sidebar dd { margin:0; text-align:right; overflow-wrap:anywhere; color:#34435b; }.capture-sidebar ul,.capture-sidebar ol { padding-left:18px; margin:0; color:#7a89a0; font-size:14px; line-height:1.9; }.capture-sidebar li + li { margin-top:10px; }.capture-sidebar p { color:#7a89a0; font-size:14px; line-height:1.9; margin:0; }.capture-sidebar p.purpose-note { padding:12px; border-radius:8px; margin-top:18px; background:#edf3fc; color:#416c9f; }
@media(max-width:1480px) { .voiceprint-setup-page { padding:22px 24px; grid-template-columns:minmax(0,1fr) 260px; gap:18px; }.capture-sidebar section { padding:20px; }.reading-text blockquote { font-size:20px; } }
@media(max-width:1150px) { .voiceprint-setup-page { grid-template-columns:1fr; }.capture-sidebar { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:720px) { .voiceprint-setup-page { padding:16px; }.capture-sidebar { grid-template-columns:1fr; }.reading-guide { padding:22px; }.reading-text { padding:18px; }.reading-text blockquote { font-size:18px; } }
</style>
