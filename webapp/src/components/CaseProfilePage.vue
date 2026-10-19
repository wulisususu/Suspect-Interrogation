<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { backendErrorMessage } from '../api/interrogation'
import { saveIdentityProfileFacts, updateCaseProfile } from '../api/caseProfile'
import type { CaseSummary, FactItem } from '../types/interrogation'
import { calculateAge } from '../utils/identityOcr'
import { createIdentityForm, identityFactValues, identityFormError } from '../utils/identityForm'
import ManualIdentityFields from './ManualIdentityFields.vue'

const props = defineProps<{ summary: CaseSummary; facts: FactItem[] }>()
const emit = defineEmits<{ saved: [] }>()

const busy = ref('')
const error = ref('')
const message = ref('')

const form = reactive(createIdentityForm())

const profileFact = (key: string) => props.facts.find((item) => item.key === key)
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
  form.officerName = props.summary.officerName || '当前警官'
  form.officerUnit = factText('officer_unit')
  form.recorderName = factText('recorder_name')
  form.recorderUnit = factText('recorder_unit', form.officerUnit)
}

watch(() => [props.summary, props.facts], syncFromProps, { deep: true, immediate: true })

async function save() {
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
      officerName: form.officerName.trim() || '当前警官',
      caseType: form.caseType.trim() || 'suspect_interrogation',
    })
    await saveIdentityProfileFacts(props.summary.id, identityFactValues(form))

    message.value = '身份、案件信息及询问笔录固定头部已保存。'
    emit('saved')
  } catch (err) {
    error.value = backendErrorMessage(err)
  } finally {
    busy.value = ''
  }
}

onMounted(syncFromProps)
</script>

<template>
  <section class="profile-page page-card manual-profile-page">
    <header class="page-card-header">
      <div><h2>{{ summary.identitySource === 'MANUAL' ? '人工录入身份信息' : '身份信息与询问资料' }}</h2><p>请对照证件原件逐项核对，保存后将用于本案询问笔录。</p></div>
      <span class="identity-source">身份来源：{{ identitySourceText }}</span>
    </header>
    <div class="profile-content profile-content-single"><div class="profile-main">
      <p v-if="summary.identitySource === 'MANUAL'" class="manual-profile-notice">人工录入信息请由另一名在场民警对照证件原件核对。保存录入信息不能替代现场身份核验。</p>
      <ManualIdentityFields :form="form" :disabled="!!busy" />
      <div v-if="error" class="page-message error" role="alert">{{ error }}</div>
      <div v-else-if="message" class="page-message success" role="status">{{ message }}</div>
      <footer class="profile-footer"><button class="profile-cancel" :disabled="!!busy" @click="syncFromProps(); error = ''; message = ''">撤销修改</button><button class="primary-action" :disabled="!!busy" @click="save">{{ busy === 'save' ? '保存中…' : '保存身份与询问资料' }}</button></footer>
      <p class="profile-lock-note">笔录冻结后，身份信息和正式问答将锁定，不能再修改。</p>
    </div></div>
  </section>
</template>

<style scoped>
.manual-profile-page { background: #fff; height: calc(100% - var(--osk-height,0px)); }
.manual-profile-page .page-card-header { align-items: flex-start; padding: 26px 30px 0; border: 0; }
.manual-profile-page h2 { font-size: 24px; color: #19345e; }
.manual-profile-page .page-card-header p { margin: 14px 0 0; color: #7a89a0; font-size: 14px; }
.identity-source { padding: 7px 12px; border-radius: 99px; background: #edf2fa; color: #58759b; font-size: 13px; white-space: nowrap; }
.profile-content.profile-content-single { display: block; overflow: auto; padding: 20px 30px 26px; scroll-padding-block: 24px; }
.profile-content-single .profile-main { width: min(1180px,100%); margin: 0 auto; }
.manual-profile-notice { margin: 0 0 20px; padding: 15px 17px; background: #fff3df; color: #aa771f; border-radius: 9px; font-size: 14px; line-height: 1.6; }
.profile-footer { display: grid; grid-template-columns: minmax(150px,1fr) 4fr; gap: 14px; border: 0; padding-top: 0; }
.profile-footer button { min-height: 52px; border-radius: 9px; font-size: 15px; font-weight: 600; }
.profile-cancel { background: #fff; border: 1px solid #dce5f1; color: #687993; }
.profile-footer .primary-action { background: #205293; }
.profile-lock-note { margin: 14px 0 0; color: #91a0b5; font-size: 13px; text-align: center; }
</style>
