<script setup lang="ts">
/** 民警签名新增 / 更换弹窗外观（样板 P32）。签名预录入尚未接入，字段与保存均禁用。 */
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div class="enroll-modal" role="dialog" aria-modal="true" aria-label="新增 / 更换民警签名">
    <section class="enroll-dialog">
      <h2>新增 / 更换民警签名</h2>
      <p>签名预先手写录入并绑定警号，签署环节一键调用；停用后不可调用但保留记录</p>
      <div class="enroll-fields">
        <label><span>警号</span><input disabled placeholder="民警警号" /></label>
        <label><span>姓名</span><input disabled placeholder="民警姓名" /></label>
      </div>
      <div class="enroll-canvas">手写签名区 · 功能待接入</div>
      <footer>
        <button type="button" class="enroll-secondary" @click="emit('close')">取消</button>
        <button type="button" class="enroll-primary" disabled>保存签名</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.enroll-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--space-5); background: rgba(22, 38, 63, 0.72); }
.enroll-dialog { display: flex; flex-direction: column; gap: var(--space-3); width: min(520px, 100%); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.enroll-dialog h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.enroll-dialog p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.enroll-fields { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.enroll-fields label { display: flex; flex-direction: column; gap: var(--space-1); color: var(--ink-500); font-size: var(--text-xs); }
.enroll-fields input { min-height: 40px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.enroll-canvas { display: grid; place-items: center; min-height: 160px; border: 1px dashed var(--line-300); border-radius: var(--radius-md); color: var(--ink-400); font-size: var(--text-sm); }
.enroll-dialog footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.enroll-primary, .enroll-secondary { min-height: 44px; padding: 0 var(--space-4); border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: 600; }
.enroll-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.enroll-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
</style>
