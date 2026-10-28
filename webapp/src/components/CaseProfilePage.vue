<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { backendErrorMessage } from '../api/interrogation'
import { saveIdentityProfileFacts, updateCaseProfile } from '../api/caseProfile'
import { branding } from '../config/branding'
import { TEMPLATE_CATALOG } from '../config/templateCatalog'
import type { CaseSummary, FactItem } from '../types/interrogation'
import { calculateAge } from '../utils/identityOcr'
import { createIdentityForm, identityCompleteness, identityFactValues, identityFormError } from '../utils/identityForm'
import IdentityFieldRow from './IdentityFieldRow.vue'

/**
 * ② 建档 · 被询问人身份信息（样板 P06）
 *
 * 单页建档：左栏读身份证与录音设置，右栏身份字段与询问信息，底部建档核对。
 * 读卡字段灰底标「身份证读取」，身份证上没有的信息白底蓝框标「手工补填」。
 */
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
const readFromCard = computed(() => props.summary.identitySource === 'ID_CARD_READER')
const readerState = computed(() => {
  if (readFromCard.value) return { ok: true, text: props.readerAvailable ? '读卡器已就绪 · 已读取成功' : '已从身份证芯片读取' }
  return props.readerAvailable ? { ok: true, text: '读卡器已就绪 · 待读取' } : { ok: false, text: '读卡器未配置 · 可手工录入' }
})
const readerNote = computed(() => {
  if (!readFromCard.value) return props.summary.identitySource === 'OCR' ? '证件图像录入 · 请对照原件核对' : '人工录入 · 请由另一名在场民警对照证件原件核对'
  const at = props.summary.identityCapturedAt
  const time = at ? new Date(at).toTimeString().slice(0, 8) : ''
  return `${time ? `读取于 ${time} · ` : ''}二代身份证芯片 · 无需手工录入`
})

const caseTypeOptions = computed(() => {
  const titles = TEMPLATE_CATALOG.map((item) => item.title)
  return form.caseType && !titles.includes(form.caseType) ? [form.caseType, ...titles] : titles
})
const ROUND_OPTIONS = ['1', '2', '3', '4', '5']

const checks = computed(() => [
  { label: '身份信息', ok: Boolean(form.suspectName.trim() && form.idNumber.trim()) },
  { label: '联系方式', ok: Boolean(form.contact.trim()) },
  { label: '现住址', ok: Boolean(form.currentAddress.trim()) },
  { label: '询问人 · 记录员', ok: Boolean(form.officerName.trim() && form.recorderName.trim()) },
  { label: '案件类型', ok: Boolean(form.caseType.trim()) },
  { label: '询问地点', ok: Boolean(form.interrogationPlace.trim()) },
])
const checked = computed(() => checks.value.filter((item) => item.ok))
const pending = computed(() => checks.value.filter((item) => !item.ok))

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
  form.officerUnit = factText('officer_unit', branding.unitName)
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
        <p class="reader-state" :class="{ ok: readerState.ok }"><i aria-hidden="true"></i>{{ readerState.text }}</p>
        <div class="reader-card">
          <strong>中华人民共和国居民身份证</strong>
          <span>姓　名　{{ form.suspectName || '—' }}</span>
          <span>性　别　{{ form.gender || '—' }}　　民　族　{{ form.nation || '—' }}</span>
          <span>出　生　{{ form.birthDate || '—' }}</span>
          <span>住　址　{{ form.idCardAddress || '—' }}</span>
          <span>公民身份号码　{{ maskedId || '—' }}</span>
        </div>
        <button type="button" class="profile-primary reader-button" disabled title="读卡请在新建询问时进行">放置身份证 · 点击读取</button>
        <small>{{ readerNote }}</small>

        <section class="reader-settings" aria-label="录音与指纹设置">
          <h2>录音与指纹设置</h2>
          <label class="setting-check" title="功能待接入">
            <input type="checkbox" checked disabled />
            <span>开启全程录音（双通道录音）——勾选后通道②全程录音随卷保存为原始文件</span>
          </label>
        </section>
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
            <IdentityFieldRow label="出生日期 / 年龄" :source="cardSource">
              <input v-model="form.birthDate" class="birth-input" type="date" :disabled="!!busy || locked" @change="form.age = calculateAge(form.birthDate)" />
              <span class="age-text">{{ form.age ? `${form.age} 岁（自动推算）` : '年龄自动推算' }}</span>
            </IdentityFieldRow>
            <IdentityFieldRow label="身份证住址" :source="cardSource"><input v-model="form.idCardAddress" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="现住址" source="MANUAL"><input v-model="form.currentAddress" placeholder="与户籍一致可直接填写，可修改" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="户籍所在地" :source="cardSource"><input v-model="form.householdRegistration" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="联系方式" source="MANUAL" required><input v-model="form.contact" inputmode="tel" autocomplete="off" :disabled="!!busy || locked" /></IdentityFieldRow>
          </div>
        </section>

        <section class="profile-card">
          <h2>询问信息</h2>
          <div class="inquiry-grid">
            <IdentityFieldRow label="案件类型" source="MANUAL" source-text="下拉选择" required>
              <select v-model="form.caseType" class="wide-select" :disabled="!!busy || locked">
                <option value="">请选择案件类型</option>
                <option v-for="option in caseTypeOptions" :key="option" :value="option">{{ option }}</option>
              </select>
            </IdentityFieldRow>
            <IdentityFieldRow label="询问地点" source="MANUAL" source-text="可修改"><input v-model="form.interrogationPlace" placeholder="如：一楼报案大厅" :disabled="!!busy || locked" /></IdentityFieldRow>
            <IdentityFieldRow label="询问人" source="MANUAL" source-text="默认当前 · 可改" required>
              <input v-model="form.officerName" class="person-name" placeholder="填写询问人" :disabled="!!busy || locked" />
              <input v-model="form.officerUnit" aria-label="询问人工作单位" placeholder="工作单位" :disabled="!!busy || locked" />
            </IdentityFieldRow>
            <IdentityFieldRow label="询问时间" source="MANUAL" source-text="自动记录" required><input value="开始询问后由系统自动记录" readonly disabled /></IdentityFieldRow>
            <IdentityFieldRow label="记录员" source="MANUAL" source-text="手工填写" required>
              <input v-model="form.recorderName" class="person-name" placeholder="填写记录员" :disabled="!!busy || locked" />
              <input v-model="form.recorderUnit" aria-label="记录员工作单位" placeholder="工作单位（同询问人可留空）" :disabled="!!busy || locked" />
            </IdentityFieldRow>
            <IdentityFieldRow label="询问次数 / 人大代表" source="MANUAL" source-text="下拉选择">
              <select v-model="form.interrogationRound" :disabled="!!busy || locked">
                <option v-for="round in ROUND_OPTIONS" :key="round" :value="round">第 {{ round }} 次</option>
                <option v-if="!ROUND_OPTIONS.includes(form.interrogationRound)" :value="form.interrogationRound">第 {{ form.interrogationRound }} 次</option>
              </select>
              <select v-model="form.peoplesRepresentative" :disabled="!!busy || locked"><option>否</option><option>是</option></select>
            </IdentityFieldRow>
          </div>
        </section>

        <div v-if="error" class="page-message error" role="alert">{{ error }}</div>
        <div v-else-if="message" class="page-message success" role="status">{{ message }}</div>

        <section class="profile-card profile-progress" aria-label="建档核对">
          <div class="progress-score">
            <strong>建档核对<span>信息完整度 {{ completeness }}%</span></strong>
            <span class="progress-track" aria-hidden="true"><span :style="{ width: `${completeness}%` }"></span></span>
          </div>
          <dl class="progress-checks">
            <div class="is-ok"><dt>已核 {{ checked.length }} 项</dt><dd>{{ checked.map((item) => item.label).join(' / ') || '—' }}</dd></div>
            <div v-if="pending.length" class="is-pending"><dt>待核 {{ pending.length }} 项</dt><dd>{{ pending.map((item) => item.label).join(' / ') }}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.profile-page { display: flex; flex-direction: column; min-height: 100%; height: calc(100% - var(--osk-height, 0px)); overflow: auto; background: var(--surface-sunken); }
.profile-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-3) var(--space-8); background: var(--surface); }
.profile-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 650; line-height: 1.25; }
.profile-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-sm); }
.profile-actions { display: flex; gap: var(--space-4); }
.profile-primary, .profile-secondary { min-height: 48px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-md); font-weight: 600; }
.profile-primary { border: 0; background: var(--primary-600); color: var(--surface); box-shadow: var(--shadow-card); }
.profile-secondary { border: 1px solid var(--primary-600); background: var(--surface); color: var(--primary-600); }

.profile-body { display: grid; flex: 1 0 auto; grid-template-columns: 420px minmax(0, 1fr); gap: var(--space-5); padding: var(--space-4) var(--space-6) var(--space-5); }
.profile-main { display: flex; flex-direction: column; gap: var(--space-3); min-width: 0; }
.profile-card { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4) var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.profile-card h2 { margin: 0; color: var(--ink-900); font-size: var(--text-base); font-weight: 650; }

.profile-reader { gap: var(--space-4); }
.profile-reader > h2 { font-size: var(--text-lg); }
.reader-state { display: flex; align-items: center; gap: var(--space-2); margin: 0; color: var(--warning-700); font-size: var(--text-sm); }
.reader-state i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.reader-state.ok { color: var(--success-700); }
.reader-card { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-4) var(--space-5); border-radius: var(--radius-md); background: var(--primary-100); color: var(--ink-700); font-family: var(--font-serif); font-size: var(--text-sm); line-height: 1.6; }
.reader-card strong { color: var(--primary-600); font-weight: 600; }
.reader-button { width: 100%; min-height: 52px; }
.profile-reader small { color: var(--ink-500); font-size: var(--text-xs); }
.reader-settings { display: flex; flex-direction: column; gap: var(--space-3); margin-top: var(--space-2); padding: var(--space-5); border-radius: var(--radius-md); box-shadow: var(--shadow-card); }
.reader-settings h2 { font-size: var(--text-md); }
.setting-check { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-radius: var(--radius-sm); background: var(--primary-50); color: var(--ink-900); font-size: var(--text-sm); line-height: 1.6; }
.setting-check input { flex: none; width: 24px; height: 24px; accent-color: var(--primary-600); }

.identity-rows { display: flex; flex-direction: column; gap: var(--space-2); }
.inquiry-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2) var(--space-4); }
.identity-rows :deep(.identity-row-control),
.inquiry-grid :deep(.identity-row-control) { display: flex; align-items: center; gap: var(--space-2); }
.inquiry-grid :deep(.identity-row) { grid-template-columns: 128px minmax(0, 1fr) auto; }
.inquiry-grid select.wide-select { flex: 1 1 auto; width: auto; }
.birth-input { flex: 0 0 180px; max-width: 180px; }
.age-text { color: var(--ink-900); font-size: var(--text-base); white-space: nowrap; }
.person-name { flex: 0 0 7em; max-width: 7em; }

.profile-progress { flex-direction: row; flex-wrap: wrap; align-items: center; gap: var(--space-5) var(--space-10); }
.progress-score { display: flex; flex-direction: column; gap: var(--space-2); }
.progress-score strong { display: flex; gap: var(--space-4); color: var(--primary-600); font-size: var(--text-sm); font-weight: 600; }
.progress-track { position: relative; width: 240px; height: 6px; border-radius: var(--radius-pill); background: var(--line-200); overflow: hidden; }
.progress-track > span { position: absolute; inset: 0 auto 0 0; background: var(--primary-600); }
.progress-checks { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; font-size: var(--text-sm); }
.progress-checks div { display: flex; gap: var(--space-4); }
.progress-checks dd { margin: 0; }
.progress-checks .is-ok { color: var(--success-700); }
.progress-checks .is-pending { color: var(--warning-700); }

@media (max-width: 1280px) { .profile-body { grid-template-columns: 340px minmax(0, 1fr); } }
@media (max-width: 1100px) { .profile-body, .inquiry-grid { grid-template-columns: 1fr; } }
</style>
