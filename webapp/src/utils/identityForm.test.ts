import { describe, expect, it } from 'vitest'
import { createIdentityForm, identityCompleteness, identityFormError, identityFactValues, intakeFormError } from './identityForm'

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

describe('new inquiry intake', () => {
  const officers = { officerName: '张伟', officerBadge: '038291', recorderName: '李明', recorderBadge: '038292' }

  it('requires both officers, and they must be different people', () => {
    const form = createIdentityForm()
    expect(intakeFormError(form, 'card')).toContain('主审民警')
    form.officerName = '张伟'
    expect(intakeFormError(form, 'card')).toContain('记录民警')
    Object.assign(form, { ...officers, recorderName: '张伟', recorderBadge: '038291' })
    expect(intakeFormError(form, 'card')).toContain('不同民警')
    // 名录不可用时手工填写姓名：同名也视为同一人
    Object.assign(form, { officerBadge: '', recorderBadge: '' })
    expect(intakeFormError(form, 'card')).toContain('不同民警')
    Object.assign(form, officers)
    expect(intakeFormError(form, 'card')).toBe('')
  })

  it('lists every missing basic field for manual entry and checks the number only for identity cards', () => {
    const form = { ...createIdentityForm(), ...officers }
    expect(intakeFormError(form, 'manual')).toBe('请填写：姓名、性别、出生日期、证件号码、案件类型。')
    Object.assign(form, { suspectName: '王某某', gender: '女', birthDate: '1992-05-14', idNumber: 'E1234567', caseType: '盗窃' })
    expect(intakeFormError(form, 'manual')).toContain('身份证号码格式')
    form.idDocumentType = '护照'
    expect(intakeFormError(form, 'manual')).toBe('')
  })
})

describe('identity completeness', () => {
  it('reports the share of the eight intake fields that are filled', () => {
    const form = createIdentityForm()
    expect(identityCompleteness(form)).toBe(0)
    Object.assign(form, { suspectName: '王某某', idNumber: '110101199205140000', gender: '女', birthDate: '1992-05-14', currentAddress: '某地', contact: '138' })
    expect(identityCompleteness(form)).toBe(75)
    Object.assign(form, { interrogationPlace: '2 号询问室', recorderName: '记录员' })
    expect(identityCompleteness(form)).toBe(100)
  })

  it('does not count whitespace as filled', () => {
    const form = createIdentityForm()
    form.suspectName = '   '
    expect(identityCompleteness(form)).toBe(0)
  })
})
