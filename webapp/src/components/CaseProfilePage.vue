<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { backendErrorMessage } from '../api/interrogation'
import { saveIdentityProfileFacts, updateCaseProfile } from '../api/caseProfile'
import type { CaseSummary, FactItem } from '../types/interrogation'
import { calculateAge } from '../utils/identityOcr'
import { createIdentityForm, identityCompleteness, identityFactValues, identityFormError } from '../utils/identityForm'
import IdentityFieldRow from './IdentityFieldRow.vue'

const props = defineProps<{ summary: CaseSummary; facts: FactItem[]; readerAvailable?: boolean; locked?: boolean }>()
const emit = defineEmits<{ saved: []; next: [] }>()

const busy = ref('')
const error = ref('')
const message = ref('')

const form = reactive(createIdentityForm())

const profileFact = (key: string) => props.facts.find((item) => item.key === key)
const cardSource = computed(() => (props.summary.identitySource === 'ID_CARD_READER' ? 'CARD' : 'MANUAL'))
const completeness = computed(() => identityCompleteness(form))
const maskedId = computed(() => (form.idNumber.length >= 8 ? `${form.idNumber.slice(0, 4)}${'*'.repeat(form.idNumber.length - 8)}${form.idNumber.slice(-4)}` : form.idNumber))
const identitySourceText = computed(() => ({ ID_CARD_READER: '身份证读取', OCR: '证件图像录入', MANUAL: '人工录入' })[props.summary.identitySource || ''] || '未标记')

function factText(key: string, fallback = '') {
  const value = profileFact(key)?.value?.trim()
  if (!value || value === '未录入') return fallback
  return value
}

function syncFromProps() {
  form.suspectName = props.summary.suspectName === '待录入' ? '' : props.summary.suspectName || ''
  form.gender = props.summary.gender || ''
  form.nation = props.summary.nation || ''
  form.birthDate = props.summary.birthDate || ''
  form.age = props.summary.age || calculateAge(form.birthDate)
  form.idDocumentType = factText('id_document_type', '身份证')
  form.idNumber = props.summary.idNumber || ''
  form.idCardAddress = props.summary.address || ''
  form.contact = factText('contact')
  form.currentAddress = factText('current_address')
  form.householdRegistration = factText('household_registration')
  form.peoplesRepresentative = factText('peoples_representative', '否')
  form.caseType = factText('case_type', props.summary.caseType === 'suspect_interrogation' ? '' : props.summary.caseType || '')
  form.interrogationRound = factText('interrogation_round', '1')
  form.interrogationPlace = factText('interrogation_place')
  form.officerName = props.summary.officerName && props.summary.officerName !== '当前警官' ? props.summary.officerName : ''
  form.officerUnit = factText('officer_unit')
  form.recorderName = factText('recorder_name')
  form.recorderUnit = factText('recorder_unit', form.officerUnit)
}

watch(() => [props.summary, props.facts], syncFromProps, { deep: true, immediate: true })

async function save(next = false) {
  if (props.locked) { if (next) emit('next'); return }
  if (busy.value) return
  const validation = identityFormError(form)
  if (validation) { error.value = validation; return }
  const name = form.suspectName.trim()
  const idNumber = form.idNumber.trim().toUpperCase()

  busy.value = 'save'
  error.value = ''
  message.value = ''
  try {
    await updateCaseProfile(props.summary.id, {
      suspectName: name,
      gender: form.gender.trim(),
      nation: form.nation.trim(),
      birthDate: form.birthDate.trim(),
      age: form.age.trim() || calculateAge(form.birthDate),
      idNumber,
      address: form.idCardAddress.trim(),
      officerName: form.officerName.trim(),
      caseType: form.caseType.trim() || 'suspect_interrogation',
    })
    await saveIdentityProfileFacts(props.summary.id, identityFactValues(form))

    message.value = '身份、案件信息及询问笔录固定头部已保存。'
    emit('saved')
    if (next) emit('next')
  } catch (err) {
    error.value = backendErrorMessage(err)
  } finally {
    busy.value = ''
  }
}

onMounted(syncFromProps)
</script>

<template>
  <section class="profile-page">
    <header class="profile-head">
      <div>
        <h1>② 建档 · 被询问人身份信息</h1>
        <p v-if="locked">笔录已冻结，身份信息只读</p>
        <p v-else>先读身份证，再补填身份证上没有的信息 · 所有信息后续均可修改</p>
      </div>
      <div class="profile-actions">
        <button type="button" class="profile-secondary" :disabled="!!busy || locked" @click="save()">{{ busy === 'save' ? '保存中…' : '暂存草稿' }}</button>
        <button type="button" class="profile-primary" :disabled="!!busy" @click="save(true)">下一步 · 问答录入 →</button>
      </div>
    </header>

    <div class="profile-body">
      <aside class="profile-card profile-reader">
        <h2>身份证读取</h2>
        <p class="reader-state" :class="{ ok: readerAvailable }">{{ readerAvailable ? '读卡器已就绪' : '读卡器未配置 · 可手工录入' }}</p>
        <div class="reader-card">
          <strong>中华人民共和国居民身份证</strong>
          <span>姓　名　{{ form.suspectName || '—' }}</span>
          <span>性　别　{{ form.gender || '—' }}　民　族　{{ form.nation || '—' }}</span>
          <span>出　生　{{ form.birthDate || '—' }}</span>
          <span>住　址　{{ form.idCardAddress || '—' }}</span>
          <span>公民身份号码　{{ maskedId || '—' }}</span>
        </div>
        <button type="button" class="profile-primary reader-button" disabled title="读卡请在新建询问时进行">放置身份证 · 点击读取</button>
        <small>身份来源：{{ identitySourceText }}</small>
        <p v-if="summary.identitySource === 'MANUAL'" class="manual-profile-notice">人工录入信息请由另一名在场民警对照证件原件核对。</p>
      </aside>

      <div class="profile-main">
        <section class="profile-card">
          <h2>被询问人身份信息</h2>
          <div class="identity-rows">
            <IdentityFieldRow label="姓名" :source="cardSource" required><input v-model="form.suspectName" autocomplete="off" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="身份证号" :source="cardSource" required><input v-model="form.idNumber" maxlength="18" autocomplete="off" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="性别 / 民族" :source="cardSource">
              <select v-model="form.gender" :disabled="!!busy || locked"><option value="">未填写</option><option>男</option><option>女</option></select>
              <input v-model="form.nation" placeholder="民族" :disabled="!!busy || locked" />
            </IdentityFieldRow>
            <IdentityFieldRow label="出生日期" :source="cardSource"><input v-model="form.birthDate" type="date" :disabled="!!busy || locked" @change="form.age = calculateAge(form.birthDate)" /></IdentityFieldRow>
            <IdentityFieldRow label="年龄" source="AUTO"><input v-model="form.age" inputmode="numeric" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="身份证住址" :source="cardSource"><input v-model="form.idCardAddress" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="现住址" source="MANUAL" required><input v-model="form.currentAddress" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="户籍所在地" source="MANUAL"><input v-model="form.householdRegistration" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="联系方式" source="MANUAL" required><input v-model="form.contact" inputmode="tel" autocomplete="off" :disabled="!!busy || locked" /></IdentityFieldRow>
          </div>
        </section>

        <section class="profile-card">
          <h2>询问信息</h2>
          <div class="inquiry-grid">
            <IdentityFieldRow label="案件类型" source="MANUAL"><input v-model="form.caseType" placeholder="选择或填写案件类型" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="询问地点" source="MANUAL" required><input v-model="form.interrogationPlace" placeholder="如：2 号询问室" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="询问人" source="MANUAL"><input v-model="form.officerName" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="询问时间" source="AUTO"><input value="开始询问后由系统自动记录" readonly disabled /></IdentityFieldRow>
            <IdentityFieldRow label="记录员" source="MANUAL" required><input v-model="form.recorderName" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="询问次数 / 人大代表" source="MANUAL">
              <input v-model="form.interrogationRound" inputmode="numeric" :disabled="!!busy || locked" />
              <select v-model="form.peoplesRepresentative" :disabled="!!busy || locked"><option>否</option><option>是</option></select>
            </IdentityFieldRow>
            <IdentityFieldRow label="询问人单位" source="MANUAL"><input v-model="form.officerUnit" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="记录人单位" source="MANUAL"><input v-model="form.recorderUnit" :disabled="!!busy || locked" /></IdentityFieldRow>
          </div>
        </section>

        <div v-if="error" class="page-message error" role="alert">{{ error }}</div>
        <div v-else-if="message" class="page-message success" role="status">{{ message }}</div>

        <section class="profile-card profile-progress" aria-label="建档核对">
          <strong>建档核对</strong>
          <span>信息完整度 {{ completeness }}%</span>
          <span class="progress-track" aria-hidden="true"><span :style="{ width: `${completeness}%` }"></span></span>
          <small>笔录冻结后，身份信息和正式问答将锁定，不能再修改。</small>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.profile-page { display: flex; flex-direction: column; gap: var(--space-5); height: calc(100% - var(--osk-height, 0px)); padding: var(--space-6); overflow: auto; }
.profile-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.profile-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-2xl); font-weight: 650; }
.profile-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.profile-actions { display: flex; gap: var(--space-3); }
.profile-primary, .profile-secondary { min-height: 44px; padding: 0 var(--space-5); border-radius: var(--radius-md); font-size: var(--text-base); font-weight: 600; }
.profile-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.profile-secondary { border: 1px solid var(--primary-500); background: var(--surface); color: var(--primary-600); }

.profile-body { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: var(--space-5); align-items: start; }
.profile-main { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.profile-card { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.profile-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-md); font-weight: 650; }

.reader-state { margin: 0; color: var(--warning-700); font-size: var(--text-xs); }
.reader-state.ok { color: var(--success-700); }
.reader-card { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-4); border-radius: var(--radius-md); background: var(--primary-100); color: var(--ink-700); font: var(--text-xs)/1.7 var(--font-serif); }
.reader-card strong { color: var(--primary-600); font-weight: 600; }
.reader-button { width: 100%; }
.profile-reader small { color: var(--ink-400); font-size: var(--text-xs); }
.manual-profile-notice { margin: 0; padding: var(--space-3); border-radius: var(--radius-sm); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-xs); line-height: 1.6; }

.identity-rows { display: flex; flex-direction: column; gap: var(--space-2); }
.inquiry-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
.identity-rows :deep(.identity-row-control),
.inquiry-grid :deep(.identity-row-control) { display: flex; gap: var(--space-2); }

.profile-progress { flex-direction: row; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.profile-progress strong { color: var(--primary-600); font-size: var(--text-sm); }
.profile-progress span { color: var(--primary-600); font-size: var(--text-sm); }
.progress-track { position: relative; flex: 0 0 200px; height: 6px; border-radius: var(--radius-pill); background: var(--line-200); overflow: hidden; }
.progress-track > span { position: absolute; inset: 0 auto 0 0; background: var(--primary-600); }
.profile-progress small { flex-basis: 100%; color: var(--ink-400); font-size: var(--text-xs); }

@media (max-width: 1100px) { .profile-body, .inquiry-grid { grid-template-columns: 1fr; } }
</style>
