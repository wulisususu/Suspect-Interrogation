<script setup lang="ts">
import { computed } from 'vue'
import { X } from '@lucide/vue'
import type { FinalizeCheck } from '../utils/reviewChecks'
import LongPressButton from './LongPressButton.vue'

/**
 * 定稿校验抽屉（样板 P08 · 状态 C）
 *
 * 从③页头「定稿并校验」唤起，在正本下半部上浮；逐项过目，检查只提示不代改。
 * 长按 0.8 秒确认定稿：正本冻结并进入⑤签署。只有后端必然拒绝的情况（blockReason）才禁用确认。
 */
const props = defineProps<{
  checks: FinalizeCheck[]
  coverage: { covered: number; total: number }
  blockReason: string
  busy: boolean
}>()

const emit = defineEmits<{ close: []; confirm: []; fullPage: [] }>()

const passed = computed(() => props.checks.filter((item) => item.state === 'pass').length)
const pending = computed(() => props.checks.length - passed.value)
</script>

<template>
  <section class="finalize-drawer record-no-print" role="dialog" aria-modal="false" aria-label="定稿前校验">
    <p class="finalize-coverage">
      <span :class="coverage.covered === coverage.total ? 'is-ok' : 'is-warn'">要素 {{ coverage.covered }}/{{ coverage.total }} 已覆盖</span>
      <button type="button" class="finalize-link" @click="emit('fullPage')">查看完整校验页 ›</button>
    </p>
    <header class="finalize-head">
      <strong>定稿前校验 · 逐项确认（只提示，不代改）</strong>
      <span>{{ checks.length }} 项检查 · {{ passed }} 项通过 · {{ pending }} 项待确认</span>
      <button type="button" class="finalize-close" aria-label="收起校验" @click="emit('close')"><X :size="18" aria-hidden="true" /></button>
    </header>
    <ul class="finalize-checks">
      <li v-for="item in checks" :key="item.key" :class="`is-${item.state}`">
        <strong>{{ item.state === 'pass' ? '通过' : item.state === 'block' ? '需处理' : '待确认' }} · {{ item.title }}</strong>
        <small v-if="item.detail">{{ item.detail }}</small>
      </li>
    </ul>
    <p v-if="blockReason" class="finalize-block" role="status">{{ blockReason }}</p>
    <footer class="finalize-actions">
      <button type="button" class="finalize-back" @click="emit('close')">返回修改</button>
      <LongPressButton class="finalize-confirm" :disabled="!!blockReason || busy" @confirm="emit('confirm')">
        {{ busy ? '正在定稿…' : '确认定稿 · 正本冻结并进入签署（长按 0.8 秒）' }}
      </LongPressButton>
    </footer>
  </section>
</template>

<style scoped>
.finalize-drawer { position: absolute; inset: auto 0 0 0; z-index: 8; display: flex; flex-direction: column; gap: var(--space-3); max-height: 72%; padding: var(--space-4) var(--space-5) var(--space-5); overflow: auto; border-top: 2px solid var(--primary-600); border-radius: var(--radius-lg) var(--radius-lg) 0 0; background: var(--surface); box-shadow: var(--shadow-pop); animation: finalize-rise 240ms ease-out; }
@keyframes finalize-rise { from { transform: translateY(24px); opacity: 0; } to { transform: none; opacity: 1; } }
.finalize-coverage { display: flex; align-items: center; justify-content: space-between; margin: 0; font-size: var(--text-sm); }
.finalize-coverage .is-ok { padding: 2px var(--space-3); border-radius: var(--radius-sm); background: var(--success-100); color: var(--success-700); font-weight: 600; }
.finalize-coverage .is-warn { padding: 2px var(--space-3); border-radius: var(--radius-sm); background: var(--warning-100); color: var(--warning-700); font-weight: 600; }
.finalize-link { border: 0; background: transparent; color: var(--primary-600); font-size: var(--text-sm); }
.finalize-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.finalize-head strong { color: var(--ink-900); font-size: var(--text-lg); font-weight: 650; }
.finalize-head span { margin-left: auto; color: var(--warning-700); font-size: var(--text-sm); }
.finalize-close { display: grid; place-items: center; width: 36px; height: 36px; border: 0; border-radius: 50%; background: var(--surface-sunken); color: var(--ink-500); }
.finalize-checks { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.finalize-checks li { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-3) var(--space-4); border-radius: var(--radius-sm); }
.finalize-checks strong { font-size: var(--text-md); font-weight: 600; }
.finalize-checks small { color: var(--ink-500); font-size: var(--text-sm); }
.finalize-checks .is-pass { background: var(--success-100); color: var(--success-700); }
.finalize-checks .is-pending { background: var(--warning-100); color: var(--warning-700); }
.finalize-checks .is-block { background: var(--danger-100); color: var(--danger-700); }
.finalize-block { margin: 0; color: var(--danger-600); font-size: var(--text-sm); }
.finalize-actions { position: sticky; bottom: calc(-1 * var(--space-5)); display: flex; gap: var(--space-3); margin: 0 calc(-1 * var(--space-5)) calc(-1 * var(--space-5)); padding: var(--space-3) var(--space-5) var(--space-5); background: var(--surface); }
.finalize-back { min-height: 52px; padding: 0 var(--space-6); border: 1px solid var(--primary-600); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-md); font-weight: 600; }
.finalize-confirm { flex: 1; min-height: 52px; border: 0; border-radius: var(--radius-sm); background: var(--primary-600); color: var(--surface); font-size: var(--text-md); font-weight: 600; }
.finalize-confirm:disabled { opacity: .55; }
</style>
