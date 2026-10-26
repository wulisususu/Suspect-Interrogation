<script setup lang="ts">
import { useId } from 'vue'
import type { IdentityForm } from '../utils/identityForm'
import { calculateAge } from '../utils/identityOcr'

defineProps<{ form: IdentityForm; disabled?: boolean }>()
const id = useId()
</script>

<template>
  <div class="manual-identity-fields">
    <fieldset :disabled="disabled" class="manual-identity-column">
      <legend>被询问人身份信息</legend>
      <label><span>姓名 <b>*</b></span><input v-model="form.suspectName" required autocomplete="off" /></label>
      <label><span>年龄（岁）</span><input v-model="form.age" inputmode="numeric" /></label>
      <label><span>性别</span><select v-model="form.gender"><option value="">未填写</option><option>男</option><option>女</option></select></label>
      <label><span>证件类型</span><input v-model="form.idDocumentType" /></label>
      <label><span>出生日期</span><input v-model="form.birthDate" type="date" @change="form.age = calculateAge(form.birthDate)" /></label>
      <label><span>联系方式</span><input v-model="form.contact" inputmode="tel" autocomplete="off" /></label>
      <label><span>是否人大代表</span><select v-model="form.peoplesRepresentative"><option>否</option><option>是</option></select></label>
      <label><span>户籍所在地</span><textarea v-model="form.householdRegistration" rows="1"></textarea></label>
      <label><span>现住址</span><textarea v-model="form.currentAddress" rows="1"></textarea></label>
    </fieldset>
    <fieldset :disabled="disabled" class="manual-identity-column">
      <legend>询问笔录头部</legend>
      <label><span>民族</span><input v-model="form.nation" /></label>
      <label><span>案件类型</span><input v-model="form.caseType" :list="id + '-case-types'" placeholder="选择或填写案件类型" /><datalist :id="id + '-case-types'"><option value="盗窃" /><option value="抢夺" /><option value="诈骗" /><option value="故意伤害" /></datalist></label>
      <label><span>公民身份号码</span><input v-model="form.idNumber" maxlength="18" autocomplete="off" /></label>
      <label><span>询问地点</span><input v-model="form.interrogationPlace" placeholder="如：2 号询问室" /></label>
      <label><span>询问时间</span><input value="开始询问后由系统自动记录" readonly /></label>
      <label><span>主审民警</span><input v-model="form.officerName" /></label>
      <label><span>记录民警</span><input v-model="form.recorderName" /></label>
      <label><span>询问次数</span><input v-model="form.interrogationRound" inputmode="numeric" /></label>
    </fieldset>
    <details class="manual-identity-extra">
      <summary>补充信息：身份证住址、民警工作单位</summary>
      <fieldset :disabled="disabled"><label class="extra-address"><span>身份证住址</span><textarea v-model="form.idCardAddress" rows="1"></textarea></label><label><span>询问人工作单位</span><input v-model="form.officerUnit" /></label><label><span>记录人工作单位</span><input v-model="form.recorderUnit" /></label></fieldset>
    </details>
  </div>
</template>

<style scoped>
.manual-identity-fields { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 18px 24px; color: var(--ink-700); font-size: 15px; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.manual-identity-column { display: flex; flex-direction: column; gap: 8px; }
legend { padding: 0 0 10px; font-size: 15px; color: var(--ink-700); font-weight: 700; }
label { display: flex; flex-direction: column; gap: 5px; min-width: 0; } label > span { color: var(--ink-400); font-size: 14px; } label b { color: var(--danger-700); font-weight: 400; }
input,select,textarea { width: 100%; min-width: 0; min-height: 44px; padding: 10px 13px; border: 1px solid var(--line-300); border-radius: 9px; background: var(--surface-sunken); color: var(--primary-700); font: inherit; line-height: 1.4; }
textarea { resize: vertical; } input:focus,select:focus,textarea:focus { outline: 2px solid var(--ink-400); outline-offset: 1px; border-color: var(--primary-600); }
input[readonly] { color: var(--ink-400); background: var(--surface-sunken); }
fieldset:disabled input,fieldset:disabled select,fieldset:disabled textarea { color: var(--ink-400); }
.manual-identity-extra { grid-column: 1/-1; border-top: 1px solid var(--line-100); padding-top: 12px; }
summary { color: var(--ink-500); font-size: 13px; cursor: pointer; }
.manual-identity-extra fieldset { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px 24px; margin-top: 14px; }
.extra-address { grid-column: 1/-1; }
@media(max-height: 800px) { .manual-identity-column { gap: 10px; } input,select,textarea { min-height: 42px; padding: 9px 12px; } }
@media(max-width: 700px) { .manual-identity-fields,.manual-identity-extra fieldset { grid-template-columns: 1fr; } }
</style>
