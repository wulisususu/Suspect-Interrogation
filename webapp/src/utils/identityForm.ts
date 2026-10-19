export function createIdentityForm() {
  return {
    suspectName: '', gender: '', nation: '', birthDate: '', age: '', idNumber: '', idCardAddress: '',
    idDocumentType: '身份证', contact: '', currentAddress: '', householdRegistration: '', peoplesRepresentative: '否',
    caseType: '', interrogationRound: '1', interrogationPlace: '', officerName: '', officerUnit: '', recorderName: '', recorderUnit: '',
  }
}

export type IdentityForm = ReturnType<typeof createIdentityForm>

export function identityFormError(form: IdentityForm): string {
  if (!form.suspectName.trim()) return '请先录入被询问人姓名。'
  const id = form.idNumber.trim().toUpperCase()
  if (id && !/^\d{15}$|^\d{17}[\dX]$/.test(id)) return '身份证号码格式不正确。'
  if (!/^\d+$/.test(form.interrogationRound.trim() || '1')) return '询问次数应填写数字。'
  return ''
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
