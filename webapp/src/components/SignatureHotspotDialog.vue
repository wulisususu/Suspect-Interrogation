<script setup lang="ts">
import { Fingerprint } from '@lucide/vue'

/**
 * 文末热区操作弹窗（样板 P14）：指纹捺印 / 民警签名预录入调用。
 * 被询问人现场手写沿用签署页的手写画板。指纹采集器与民警预录签名尚未接入，
 * 确认按钮保持禁用，民警可改为现场手写。
 */
defineProps<{
  role: 'FINGERPRINT' | 'OFFICER'
  officers: Array<{ officerId: string; officerName: string }>
  busy: boolean
}>()
const emit = defineEmits<{ cancel: []; handwrite: [] }>()
</script>

<template>
  <div class="hotspot-modal" role="dialog" aria-modal="true" :aria-label="role === 'FINGERPRINT' ? '指纹捺印' : '民警签名'">
    <section class="hotspot-dialog">
      <template v-if="role === 'FINGERPRINT'">
        <h2>指纹捺印 · 现场采集</h2>
        <p class="hotspot-dialog-hint">请将被询问人手指按压于采集窗，录入 1 枚即可</p>
        <div class="fingerprint-window">
          <Fingerprint :size="44" aria-hidden="true" />
          <strong>0 / 1 枚 · 请按压采集窗</strong>
        </div>
        <p class="hotspot-dialog-note">本机未接入采集器，捺印按纸质流程在打印件上办理</p>
        <footer>
          <button type="button" class="hotspot-dialog-secondary" @click="emit('cancel')">关闭</button>
          <button type="button" class="hotspot-dialog-primary" disabled>确认捺印并写入</button>
        </footer>
      </template>

      <template v-else>
        <h2>民警签名 · 预录入调用</h2>
        <p class="hotspot-dialog-hint">选择民警，调用其预录入签名写入文书文末热区</p>
        <ul v-if="officers.length" class="officer-list">
          <li v-for="officer in officers" :key="officer.officerId">
            <span>{{ officer.officerName }}（{{ officer.officerId }}）</span>
            <small>未预录入签名</small>
          </li>
        </ul>
        <p v-else class="hotspot-dialog-empty">民警声纹库中暂无民警，可改为现场手写</p>
        <p class="hotspot-dialog-note">民警签名预录入管理尚未接入；改为现场手写同样写入文书并留痕</p>
        <footer>
          <button type="button" class="hotspot-dialog-secondary" @click="emit('cancel')">取消</button>
          <button type="button" class="hotspot-dialog-secondary" :disabled="busy" @click="emit('handwrite')">改为现场手写</button>
          <button type="button" class="hotspot-dialog-primary" disabled>确认调用并写入</button>
        </footer>
      </template>
    </section>
  </div>
</template>

<style scoped>
.hotspot-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--space-5); background: rgba(22, 38, 63, 0.72); }
.hotspot-dialog { display: flex; flex-direction: column; gap: var(--space-3); width: min(440px, 100%); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-pop); }
.hotspot-dialog h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.hotspot-dialog-hint { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.fingerprint-window { display: grid; place-items: center; gap: var(--space-3); min-height: 160px; border: 1px solid var(--primary-500); border-radius: var(--radius-md); background: var(--primary-50); color: var(--primary-600); font-size: var(--text-sm); }
.officer-list { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.officer-list li { display: flex; align-items: center; justify-content: space-between; min-height: 52px; padding: 0 var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-md); color: var(--ink-700); font-size: var(--text-sm); }
.officer-list small { color: var(--ink-400); font-size: var(--text-xs); }
.hotspot-dialog-empty { margin: 0; padding: var(--space-4); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-sm); text-align: center; }
.hotspot-dialog-note { margin: 0; color: var(--warning-700); font-size: var(--text-xs); }
.hotspot-dialog footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.hotspot-dialog-primary, .hotspot-dialog-secondary { min-height: 44px; padding: 0 var(--space-4); border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: 600; }
.hotspot-dialog-primary { border: 0; background: var(--primary-600); color: var(--surface); }
.hotspot-dialog-secondary { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
</style>
