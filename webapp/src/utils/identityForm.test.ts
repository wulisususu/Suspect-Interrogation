import { describe, expect, it } from 'vitest'
import { createIdentityForm, identityFormError, identityFactValues } from './identityForm'

describe('manual identity information', () => {
  it('rejects invalid names, identity numbers and inquiry counts before saving', () => {
    const form = createIdentityForm()
    expect(identityFormError(form)).toContain('姓名')
    form.suspectName = '界面测试'
    form.idNumber = '123'
    expect(identityFormError(form)).toContain('身份证')
    form.idNumber = '11010119900101001x'
    form.interrogationRound = '第1次'
    expect(identityFormError(form)).toContain('询问次数')
    form.interrogationRound = '2'
    expect(identityFormError(form)).toBe('')
  })

  it('maps both columns to existing fact keys without dropping supplemental fields', () => {
    const form = { ...createIdentityForm(), caseType: ' 诈骗 ', contact: ' 13800000000 ', householdRegistration: ' 户籍地址 ', currentAddress: ' 现住地址 ', interrogationPlace: ' 2号询问室 ', recorderName: ' 记录民警 ', interrogationRound: '2' }
    expect(identityFactValues(form)).toEqual({
      case_type: '诈骗', contact: '13800000000', household_registration: '户籍地址', current_address: '现住地址',
      interrogation_place: '2号询问室', recorder_name: '记录民警', interrogation_round: '2',
      id_document_type: '身份证', peoples_representative: '否', officer_unit: '', recorder_unit: '',
    })
  })
})
