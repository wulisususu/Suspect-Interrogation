<script setup lang="ts">
import { useId } from 'vue'
import type { IdentityForm } from '../utils/identityForm'
import { calculateAge } from '../utils/identityOcr'

/**
 * 新建询问 · 人工录入：只收建案必需的基本身份信息（全部必填）。
 * 联系方式、住址、户籍、询问地点、询问次数、是否人大代表等在「②建档」页补填。
 */
defineProps<{ form: IdentityForm; disabled?: boolean }>()
const id = useId()
</script>

<template>
  <fieldset :disabled="disabled" class="manual-identity-fields">
    <legend>被询问人基本信息<small>均为必填</small></legend>
    <label><span>姓名 <b>*</b></span><input v-model="form.suspectName" aria-required="true" autocomplete="off" /></label>
    <label><span>性别 <b>*</b></span><select v-model="form.gender" aria-required="true"><option value="">请选择</option><option>男</option><option>女</option></select></label>
    <label>
      <span>出生日期 <b>*</b><em v-if="form.age">{{ form.age }} 岁</em></span>
      <input v-model="form.birthDate" type="date" aria-required="true" @change="form.age = calculateAge(form.birthDate)" />
    </label>
    <label><span>民族</span><input v-model="form.nation" placeholder="如：汉" /></label>
    <label>
      <span>证件类型</span>
      <input v-model="form.idDocumentType" :list="id + '-doc-types'" />
      <datalist :id="id + '-doc-types'"><option value="身份证" /><option value="护照" /><option value="港澳居民来往内地通行证" /><option value="台湾居民来往大陆通行证" /></datalist>
    </label>
    <label><span>证件号码 <b>*</b></span><input v-model="form.idNumber" maxlength="18" aria-required="true" autocomplete="off" /></label>
    <label class="span-2">
      <span>案件类型 <b>*</b></span>
      <input v-model="form.caseType" :list="id + '-case-types'" aria-required="true" placeholder="选择或填写案件类型" />
      <datalist :id="id + '-case-types'"><option value="盗窃" /><option value="抢夺" /><option value="诈骗" /><option value="故意伤害" /></datalist>
    </label>
    <p class="later-note span-2">联系方式、现住址、户籍所在地、询问地点、询问次数、是否人大代表等，进入「②建档」页后补填。</p>
  </fieldset>
</template>

<style scoped>
.manual-identity-fields { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px 24px; min-width: 0; margin: 0; padding: 0; border: 0; color: var(--ink-700); font-size: var(--text-md); }
legend { display: flex; align-items: baseline; gap: 10px; padding: 0 0 10px; font-size: var(--text-md); color: var(--ink-700); font-weight: 700; }
legend small { color: var(--ink-400); font-size: var(--text-sm); font-weight: 400; }
label { display: flex; flex-direction: column; gap: 5px; min-width: 0; } label > span { display: flex; gap: 8px; color: var(--ink-400); font-size: var(--text-base); } label b { color: var(--danger-700); font-weight: 400; }
label em { margin-left: auto; color: var(--ink-500); font-style: normal; }
.span-2 { grid-column: 1/-1; }
input,select { width: 100%; min-width: 0; min-height: 44px; padding: 10px 13px; border: 1px solid var(--line-300); border-radius: 9px; background: var(--surface-sunken); color: var(--primary-700); font: inherit; line-height: 1.4; }
input:focus,select:focus { outline: 2px solid var(--ink-400); outline-offset: 1px; border-color: var(--primary-600); }
fieldset:disabled input,fieldset:disabled select { color: var(--ink-400); }
.later-note { margin: 4px 0 0; padding-top: 12px; border-top: 1px solid var(--line-100); color: var(--ink-500); font-size: var(--text-sm); }
@media(max-height: 800px) { .manual-identity-fields { gap: 10px 24px; } input,select { min-height: 42px; padding: 9px 12px; } }
@media(max-width: 700px) { .manual-identity-fields { grid-template-columns: 1fr; } }
</style>
