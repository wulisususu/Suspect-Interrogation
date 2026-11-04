export function createIdentityForm() {
  return {
    suspectName: '', gender: '', nation: '', birthDate: '', age: '', idNumber: '', idCardAddress: '',
    idDocumentType: '身份证', contact: '', currentAddress: '', householdRegistration: '', peoplesRepresentative: '否',
    caseType: '', interrogationRound: '1', interrogationPlace: '', officerName: '', officerUnit: '', recorderName: '', recorderUnit: '',
    /** 从民警名录选择时的警号；手工填写姓名时为空 */
    officerBadge: '', recorderBadge: '',
  }
}

export type IdentityForm = ReturnType<typeof createIdentityForm>

export function identityFormError(form: IdentityForm): string {
  if (!form.suspectName.trim()) return '请先录入被询问人姓名。'
  const id = form.idNumber.trim().toUpperCase()
  const idCard = ['', '身份证'].includes(form.idDocumentType.trim())
  if (id && idCard && !/^\d{15}$|^\d{17}[\dX]$/.test(id)) return '身份证号码格式不正确。'
  if (!/^\d+$/.test(form.interrogationRound.trim() || '1')) return '询问次数应填写数字。'
  return ''
}

/** 本案两名民警：都必须指定，且不能是同一人。 */
export function officerPairError(form: IdentityForm): string {
  if (!form.officerName.trim()) return '请选择主审民警，该民警会作为建案操作的留痕人。'
  if (!form.recorderName.trim()) return '请选择记录民警。'
  const same = form.officerBadge && form.recorderBadge
    ? form.officerBadge === form.recorderBadge
    : form.officerName.trim() === form.recorderName.trim()
  return same ? '主审民警与记录民警应为不同民警。' : ''
}

/** 新建询问弹窗的必填项，未填时返回需补的项目名；联系方式、住址、询问地点等在②建档页补填。 */
const INTAKE_REQUIRED = [
  ['suspectName', '姓名'], ['gender', '性别'], ['birthDate', '出生日期'], ['idNumber', '证件号码'], ['caseType', '案件类型'],
] as const

export function intakeFormError(form: IdentityForm, mode: 'card' | 'manual'): string {
  const officers = officerPairError(form)
  if (officers) return officers
  if (mode === 'card') return ''
  const missing = INTAKE_REQUIRED.filter(([key]) => !form[key].trim()).map(([, label]) => label)
  if (missing.length) return `请填写：${missing.join('、')}。`
  return identityFormError(form)
}

export function identityFactValues(form: IdentityForm): Record<string, string> {
  return Object.fromEntries(Object.entries({
    current_address: form.currentAddress, case_type: form.caseType,
    interrogation_round: form.interrogationRound.trim() || '1', interrogation_place: form.interrogationPlace,
    officer_unit: form.officerUnit, recorder_name: form.recorderName, recorder_unit: form.recorderUnit,
    id_document_type: form.idDocumentType.trim() || '身份证', peoples_representative: form.peoplesRepresentative,
    contact: form.contact, household_registration: form.householdRegistration,
  }).map(([key, value]) => [key, value.trim()]))
}

/** 建档核对的必填项：身份、联系与询问地点、记录人。 */
const COMPLETENESS_FIELDS = ['suspectName', 'idNumber', 'gender', 'birthDate', 'currentAddress', 'contact', 'interrogationPlace', 'recorderName'] as const

export function identityCompleteness(form: IdentityForm): number {
  const filled = COMPLETENESS_FIELDS.filter((key) => form[key].trim()).length
  return Math.round((filled / COMPLETENESS_FIELDS.length) * 100)
}
