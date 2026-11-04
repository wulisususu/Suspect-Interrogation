<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight } from '@lucide/vue'
import type { CaseSummary, FactItem } from '../types/interrogation'
import { birthText, maskIdNumber, maskPhone } from '../utils/selfService'

/**
 * 自助模式 · ②建档：本人核对身份（样板「自助式模式 · 身份确认」）
 *
 * 身份信息由民警读卡建档时带出，本人只核对、勾选「以上信息无误」；有误或读取失败时
 * 请民警补填。勾选后才能开始回答。联系方式与现住址由本人核对，缺失时民警协助补填。
 */
const props = defineProps<{
  summary: CaseSummary
  facts: FactItem[]
  officerName: string
  caseType: string
  confirmed: boolean
  busy: boolean
}>()

const emit = defineEmits<{ confirm: [value: boolean]; start: []; fix: []; help: [] }>()

function fact(key: string) {
  const value = props.facts.find((item) => item.key === key)?.value?.trim()
  return value && value !== '未录入' ? value : ''
}

const name = computed(() => (props.summary.suspectName && props.summary.suspectName !== '待录入' ? props.summary.suspectName : ''))
const officer = computed(() => props.officerName || '在场民警')
const identityRows = computed(() => [
  { label: '姓　名', value: name.value },
  { label: '性　别', value: props.summary.gender || '', extra: { label: '民　族', value: props.summary.nation || '' } },
  { label: '出生日期', value: birthText(props.summary.birthDate) },
  { label: '身份证号', value: maskIdNumber(props.summary.idNumber) },
  { label: '住　址', value: props.summary.address || '' },
])
const sourceText = computed(() => (props.summary.identitySource === 'MANUAL' ? '（民警已手工录入）' : '（民警已从身份证芯片读取）'))
const contact = computed(() => maskPhone(fact('contact')))
const currentAddress = computed(() => fact('current_address'))
</script>

<template>
  <section class="ss-identity">
    <article class="ss-card ss-identity-main" aria-labelledby="ss-hello">
      <h1 id="ss-hello">您好，{{ name || '请核对身份' }}</h1>
      <p class="ss-lead">接下来由您自己回答问题。我们会把您说的话转成文字，最后由民警{{ officer }}确认后形成笔录。</p>

      <dl class="ss-id-box">
        <div v-for="row in identityRows" :key="row.label" class="ss-id-row">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value || '未读取' }}</dd>
          <template v-if="row.extra">
            <dt class="ss-id-extra">{{ row.extra.label }}</dt>
            <dd>{{ row.extra.value || '未读取' }}</dd>
          </template>
        </div>
        <p class="ss-id-source">您的身份信息<span>{{ sourceText }}</span></p>
      </dl>

      <div class="ss-confirm-row">
        <label class="ss-check">
          <input type="checkbox" :checked="confirmed" :disabled="busy" @change="emit('confirm', ($event.target as HTMLInputElement).checked)" />
          <span>以上信息无误</span>
        </label>
        <button type="button" class="ss-link" @click="emit('fix')">信息有误或读取失败，请找民警手工补填</button>
      </div>

      <div class="ss-info-box">
        <p class="ss-info-line">
          <b>联系方式</b><i aria-hidden="true">·</i><span>{{ contact || '未填写' }}</span>
          <em aria-hidden="true">|</em>
          <b>现住址</b><i aria-hidden="true">·</i><span>{{ currentAddress || '未填写' }}</span>
        </p>
        <small>以上两项由本人填写或核对，缺失时可找在场民警协助补填。</small>
      </div>

      <div class="ss-info-box">
        <p class="ss-info-line"><b>报案类型</b><i aria-hidden="true">·</i><span>{{ caseType || '未选择' }}</span></p>
        <small>如与实际情况不符，请告知在场民警更正。</small>
      </div>
    </article>

    <article class="ss-card ss-identity-notice" aria-labelledby="ss-notice-title">
      <h2 id="ss-notice-title">开始之前，请知悉</h2>
      <ol class="ss-notice-list">
        <li><b>1</b>本次问答由您本人回答，机器只负责录音和转成文字。</li>
        <li><b>2</b>您说的每一句都会记录在案，录音原件也会保留，日后可能需要与您核对。</li>
        <li><b>3</b>所有内容要由在场民警{{ officer }}核对确认后，才会形成正式的询问笔录。</li>
      </ol>

      <div class="ss-notice-actions">
        <div class="ss-buttons">
          <button type="button" class="ss-primary" :disabled="!confirmed || busy" @click="emit('start')">开始回答<ArrowRight :size="18" aria-hidden="true" /></button>
          <button type="button" class="ss-secondary" @click="emit('help')">我不太清楚，请找民警</button>
        </div>
        <p v-if="!confirmed" class="ss-hint">请先核对左侧身份信息并勾选「以上信息无误」</p>
        <p class="ss-recording-note"><b>4</b>全程录音默认开启，用于留存原始记录（含本屏告知过程）；如需关闭，请告知在场民警由其操作。</p>
      </div>
    </article>
  </section>
</template>

<style scoped>
.ss-identity { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: var(--space-6); min-height: 100%; padding: var(--space-6) var(--space-8); }
.ss-card { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-8); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-card); }

.ss-identity-main h1 { margin: 0; color: var(--ink-900); font-size: var(--text-display); font-weight: 650; }
.ss-lead { margin: calc(var(--space-2) * -1) 0 0; color: var(--ink-500); font-size: var(--text-md); line-height: 1.6; }

.ss-id-box { display: flex; flex-direction: column; gap: var(--space-3); margin: 0; padding: var(--space-5) var(--space-5) var(--space-4); border-radius: var(--radius-md); background: var(--surface-sunken); }
.ss-id-row { display: flex; align-items: baseline; gap: var(--space-4); color: var(--ink-900); font-size: var(--text-md); }
.ss-id-row dt { flex: none; min-width: 4.5em; color: var(--ink-700); }
.ss-id-row dd { margin: 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.ss-id-row .ss-id-extra { margin-left: var(--space-6); }
.ss-id-source { margin: var(--space-1) 0 0; color: var(--ink-400); font-size: var(--text-xs); }
.ss-id-source span { margin-left: var(--space-4); }

.ss-confirm-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
.ss-check { display: inline-flex; align-items: center; gap: var(--space-3); color: var(--ink-900); font-size: var(--text-lg); cursor: pointer; }
.ss-check input { width: 26px; height: 26px; accent-color: var(--primary-600); }
.ss-link { min-height: 44px; padding: 0; border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-sm); text-align: right; }

.ss-info-box { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-4) var(--space-5); border-radius: var(--radius-md); background: var(--primary-50); }
.ss-info-line { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); margin: 0; color: var(--ink-900); font-size: var(--text-md); }
.ss-info-line b { color: var(--navy-800); font-weight: 600; }
.ss-info-line i { font-style: normal; color: var(--ink-500); }
.ss-info-line em { margin: 0 var(--space-3); color: var(--ink-300); font-style: normal; }
.ss-info-box small { color: var(--ink-500); font-size: var(--text-xs); }

.ss-identity-notice h2 { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 650; }
.ss-notice-list { display: flex; flex-direction: column; gap: var(--space-5); margin: 0; padding: 0; list-style: none; color: var(--ink-700); font-size: var(--text-md); line-height: 1.6; }
.ss-notice-list li { display: flex; align-items: flex-start; gap: var(--space-4); }
.ss-notice-list b, .ss-recording-note b { display: grid; place-items: center; flex: none; width: 30px; height: 30px; border-radius: 50%; background: var(--primary-50); color: var(--primary-600); font-size: var(--text-sm); }

.ss-notice-actions { display: flex; flex-direction: column; gap: var(--space-4); margin-top: auto; }
.ss-buttons { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.ss-primary, .ss-secondary { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); min-height: 58px; padding: 0 var(--space-8); border-radius: var(--radius-md); font-size: var(--text-lg); font-weight: 600; }
.ss-primary { border: 0; background: var(--primary-600); color: var(--surface); box-shadow: var(--shadow-active); }
.ss-primary:hover:not(:disabled) { background: var(--primary-700); }
.ss-primary:disabled { opacity: 0.5; box-shadow: none; cursor: default; }
.ss-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); font-weight: 500; }
.ss-hint { margin: 0; color: var(--warning-700); font-size: var(--text-sm); }
.ss-recording-note { display: flex; align-items: center; gap: var(--space-3); margin: 0; color: var(--ink-500); font-size: var(--text-sm); }
.ss-recording-note b { background: var(--success-700); color: var(--surface); }

@media (max-width: 1100px) {
  .ss-identity { grid-template-columns: 1fr; padding: var(--space-4); }
}
</style>
