<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ArrowRight, CreditCard, LoaderCircle, ShieldCheck, X } from '@lucide/vue'
import { backendErrorMessage, createCaseWithIdentity, fetchRuntimeCapabilities } from '../api/interrogation'
import { getRuntimeAdapter, type RuntimeCapabilities } from '../runtime'
import type { CaseSummary } from '../types/interrogation'
import { calculateAge } from '../utils/identityOcr'
import { createIdentityForm, identityFactValues, identityFormError } from '../utils/identityForm'
import { saveIdentityProfileFacts } from '../api/caseProfile'
import ManualIdentityFields from './ManualIdentityFields.vue'

const emit = defineEmits<{ close: []; created: [item: CaseSummary] }>()
interface IdentityReadResponse { identity?: { name?: string; id_number?: string; sex?: string; nation?: string; birth_date?: string; address?: string } }
const capabilities = ref<RuntimeCapabilities | null>(null)
const busy = ref('')
const error = ref('')
const cardApplied = ref(false)
const mode = ref<'card' | 'manual'>('card')
const createdCase = ref<CaseSummary | null>(null)
const modalElement = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
const identityAvailable = computed(() => capabilities.value?.identity.state === 'AVAILABLE')
// 主审民警不再预填"当前警官"占位串：该值会原样写入建案审计的操作人，
// 占位文字等于伪造操作人。留空则要求现场填写。
const form = reactive({ ...createIdentityForm(), officerName: '' })
function syncAge() { form.age = calculateAge(form.birthDate) }
function selectMode(next: 'card' | 'manual') {
  if (busy.value || createdCase.value) return
  mode.value = next
  error.value = ''
  if (next === 'manual') cardApplied.value = false
  void nextTick(() => modalElement.value?.querySelector<HTMLElement>('button')?.focus())
}
function close() {
  if (busy.value) return
  if (createdCase.value) emit('created', createdCase.value)
  else emit('close')
}
function onEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
  if (event.key !== 'Tab') return
  const controls = modalElement.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')
  if (!controls?.length) return
  const first = controls[0]; const last = controls[controls.length - 1]
  if (!modalElement.value?.contains(document.activeElement)) { event.preventDefault(); first?.focus(); return }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}

async function readCard() {
  if (!identityAvailable.value) { error.value = capabilities.value?.identity.reason || '身份证读卡器尚未配置，请手动录入。'; return }
  busy.value = 'card'; error.value = ''
  try {
    const result = await getRuntimeAdapter().invoke<IdentityReadResponse>('identity.read', { actorId: form.officerName.trim() || undefined }, { timeoutMs: 30_000 })
    const identity = result.identity
    if (!identity?.name && !identity?.id_number) throw new Error('读卡器未返回可核对的身份字段')
    form.suspectName = identity.name || form.suspectName
    form.idNumber = (identity.id_number || form.idNumber).toUpperCase()
    form.gender = identity.sex || form.gender; form.nation = identity.nation || form.nation; form.birthDate = identity.birth_date || form.birthDate; form.idCardAddress = identity.address || form.idCardAddress
    syncAge(); cardApplied.value = true
  } catch (cause) { error.value = backendErrorMessage(cause) } finally { busy.value = '' }
}

async function submit() {
  if (busy.value || (mode.value === 'card' && !cardApplied.value)) return
  const validation = identityFormError(form)
  if (validation) { error.value = validation; return }
  const officerName = form.officerName.trim()
  if (!officerName) { error.value = '请填写主审民警姓名，该姓名会作为建案操作的留痕人。'; return }
  const suspectName = form.suspectName.trim(); const idNumber = form.idNumber.trim().toUpperCase()
  busy.value = 'submit'; error.value = ''
  try {
    const item = createdCase.value || await createCaseWithIdentity({
      operatorId: officerName,
      officerName,
      caseType: mode.value === 'manual' ? form.caseType.trim() || 'suspect_interrogation' : 'suspect_interrogation',
      age: form.age.trim() || calculateAge(form.birthDate),
      identity: {
        name: suspectName,
        gender: form.gender.trim(),
        nation: form.nation.trim(),
        birthDate: form.birthDate.trim(),
        idNumber,
        address: form.idCardAddress.trim(),
        source: cardApplied.value ? 'ID_CARD_READER' : 'MANUAL',
      },
    })
    createdCase.value = item
    if (mode.value === 'manual') await saveIdentityProfileFacts(item.id, identityFactValues(form))
    emit('created', item)
  } catch (cause) { error.value = (createdCase.value ? '案件已创建，部分补充资料保存失败。可重试保存，不会重复建案；也可进入已建案件补充。' : '') + backendErrorMessage(cause) } finally { busy.value = '' }
}
onMounted(async () => { previousFocus = document.activeElement as HTMLElement | null; modalElement.value?.querySelector<HTMLElement>('button')?.focus(); document.addEventListener('keydown', onEscape); try { capabilities.value = await fetchRuntimeCapabilities() } catch (cause) { error.value = backendErrorMessage(cause) } })
onUnmounted(() => { document.removeEventListener('keydown', onEscape); previousFocus?.focus() })
</script>

<template>
  <div class="identity-mask" :class="{ 'manual-entry-mode': mode === 'manual' }" @click.self="close"><section ref="modalElement" class="identity-modal" role="dialog" aria-modal="true" aria-labelledby="intake-title" :aria-busy="!!busy">
    <header><div><h2 id="intake-title">{{ mode === 'manual' ? '人工录入身份信息' : '新建询问' }}</h2><p v-if="mode === 'manual'" class="intake-subtitle">请对照证件原件逐项填写，核对后进入询问准备。</p></div><div class="intake-header-actions"><span v-if="mode === 'manual'" class="review-reminder">需现场复核</span><button v-if="mode === 'manual' && !createdCase" type="button" class="back-to-card" :disabled="!!busy" @click="selectMode('card')">返回读卡</button><button class="close-button" type="button" aria-label="关闭新建询问" :disabled="!!busy" @click="close"><X :size="21" /></button></div></header>
    <div v-if="mode === 'card'" class="intake-tabs" aria-label="身份信息录入方式"><button type="button" class="active" aria-pressed="true" :disabled="!!busy" @click="selectMode('card')">身份证读取（推荐）</button><button type="button" aria-pressed="false" :disabled="!!busy" @click="selectMode('manual')">人工录入</button></div>
    <form @submit.prevent="submit">
      <template v-if="mode === 'card'">
        <div class="identity-card" aria-live="polite"><CreditCard v-if="!cardApplied" :size="34" /><ShieldCheck v-else :size="34" /><strong>{{ cardApplied ? '身份证信息已读取，请核对以下内容' : '请将居民身份证平放至读卡器感应区' }}</strong><span :class="{ available: cardApplied }">{{ cardApplied ? '读取完成，请核对证件原件与本人信息' : capabilities ? identityAvailable ? '读卡器已就绪' : capabilities.identity.reason || '读卡器未配置，可切换人工录入' : '正在检查读卡器…' }}</span><button type="button" :disabled="!!busy || !identityAvailable" @click="readCard"><LoaderCircle v-if="busy === 'card'" :size="16" class="spinning" />{{ busy === 'card' ? '读取中…' : cardApplied ? '重新读取' : '读取身份证' }}</button></div>
        <dl class="identity-summary"><div v-for="row in [{ label: '姓名', value: form.suspectName }, { label: '公民身份号码', value: form.idNumber }, { label: '性别', value: form.gender }, { label: '民族', value: form.nation }, { label: '出生日期', value: form.birthDate }, { label: '年龄', value: form.age ? form.age + ' 岁' : '' }, { label: '身份证住址', value: form.idCardAddress }]" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ cardApplied ? row.value || '未读取到' : '待读取' }}</dd></div><div><dt><label for="intake-card-officer">主审民警</label></dt><dd><input id="intake-card-officer" v-model="form.officerName" :disabled="!!busy" placeholder="填写主审民警姓名" /></dd></div></dl>
      </template>
      <template v-else><p class="manual-notice">人工录入信息请由另一名在场民警对照证件原件核对。保存录入信息不能替代现场身份核验。</p><ManualIdentityFields :form="form" :disabled="!!busy || !!createdCase" /></template>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <footer><button type="button" class="cancel-button" :disabled="!!busy" @click="close">{{ createdCase ? '进入已建案件补充' : '取消' }}</button><button class="primary" :disabled="!!busy || (mode === 'card' && !cardApplied)">{{ busy === 'submit' ? '保存中…' : createdCase ? '重试保存补充资料' : mode === 'manual' ? '保存并进入询问准备' : '下一步：询问准备' }}<ArrowRight :size="18" /></button></footer>
    </form>
  </section></div>
</template>

<style scoped>
.identity-mask { position: fixed; inset: 0; z-index: 1400; display: grid; place-items: center; padding: 24px; background: rgba(10,22,40,.78); color: var(--ink-700); }
.identity-modal { width: min(660px,96vw); max-height: 94vh; overflow: auto; padding: 28px; border-radius: 16px; background: var(--surface); box-shadow: 0 24px 76px rgba(6,20,33,.25); font-size: var(--text-md); }
.manual-entry-mode { padding-top: 16px; padding-bottom: calc(16px + var(--osk-height,0px)); }
.manual-entry-mode .identity-modal { width: min(1180px,calc(100vw - 48px)); max-height: calc(100dvh - var(--osk-height,0px) - 32px); padding: 30px 32px; scroll-padding-block: 24px; }
.manual-entry-mode header { align-items: flex-start; margin-bottom: 18px; }
.manual-entry-mode h2 { color: var(--primary-700); font-weight: 700; font-size: var(--text-2xl); }
.intake-subtitle { margin: 14px 0 0; color: var(--ink-400); font-size: var(--text-base); }
.intake-header-actions { display: flex; align-items: center; gap: 12px; }
.review-reminder { border-radius: 99px; background: var(--warning-100); color: var(--warning-600); padding: 7px 12px; font-size: var(--text-sm); white-space: nowrap; }
.back-to-card { background: transparent; padding: 5px 0; font-size: var(--text-sm); color: var(--ink-500); }
.manual-entry-mode footer { grid-template-columns: minmax(150px,1fr) 4fr; margin-top: 18px; }
.manual-entry-mode footer button { min-height: 52px; }
.manual-entry-mode .cancel-button { background: var(--surface); border: 1px solid var(--primary-100); }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
h2 { font-size: var(--text-xl); font-weight: 650; margin: 0; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 0; border-radius: 9px; padding: 12px 16px; color: var(--ink-500); background: var(--surface-sunken); font-size: var(--text-md); }
.close-button { padding: 4px; background: transparent; color: var(--ink-400); }
.intake-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 18px; }
.intake-tabs .active,.primary { background: var(--primary-600); color: var(--surface); }
.identity-card { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 24px 15px; margin-bottom: 18px; border-radius: 12px; background: var(--primary-100); color: var(--primary-600); text-align: center; }
.identity-card strong { font-weight: 650; }
.identity-card span { font-size: var(--text-sm); color: var(--ink-500); }
.identity-card span.available { color: var(--success-700); }
.identity-card button { background: var(--surface); color: var(--primary-600); border: 1px solid var(--primary-100); padding: 8px 20px; }
.identity-summary { margin: 0 0 18px; padding: 16px 18px; background: var(--surface-sunken); border-radius: 11px; }
.identity-summary > div { display: grid; grid-template-columns: 120px 1fr; gap: 12px; align-items: center; min-height: 32px; }
dt { color: var(--ink-400); font-size: var(--text-base); } dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
.identity-summary input { text-align: right; min-height: 30px; border: 0; padding: 3px 6px; width: 100%; background: var(--primary-100); }
.manual-notice { margin: 0 0 20px; padding: 15px 17px; background: var(--warning-100); color: var(--warning-600); border-radius: 9px; font-size: var(--text-base); line-height: 1.6; }
input,select,textarea { width: 100%; min-width: 0; min-height: 42px; border: 1px solid var(--primary-100); padding: 10px 12px; border-radius: 8px; background: var(--surface-sunken); color: var(--ink-700); font: inherit; }
input:focus,select:focus,textarea:focus { outline: 2px solid var(--ink-400); outline-offset: 1px; }
.error { margin: 12px 0; padding: 10px; border-radius: 7px; background: var(--danger-100); color: var(--danger-600); }
footer { display: grid; grid-template-columns: 1fr 2fr; gap: 14px; margin-top: 18px; } footer button { min-height: 50px; }
.spinning { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media(max-height: 800px) { .identity-modal { padding: 22px 26px; } header { margin-bottom: 16px; } .identity-card { padding: 16px; gap: 8px; } .identity-summary { padding: 12px 16px; } .identity-summary > div { min-height: 29px; } }
@media(max-width: 600px) { .identity-mask { padding: 12px; } .identity-modal { padding: 20px; } .manual-form { grid-template-columns: 1fr; } .identity-summary > div { grid-template-columns: 100px 1fr; } }
</style>
