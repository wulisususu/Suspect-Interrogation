<script setup lang="ts">
import type { Officer } from '../api/officers'

/**
 * 主审民警 / 记录民警选择：名录可用时从启用民警里下拉选择（显示姓名与警号），
 * 名录不可用时退回手工填写姓名。单根元素，输入框样式沿用所在表单。
 */
const props = defineProps<{
  name: string
  badge: string
  officers: Officer[]
  available: boolean
  /** 已被另一角色选中的警号：询问人与记录员须为不同民警 */
  exclude?: string
  disabled?: boolean
  placeholder?: string
  ariaLabel?: string
}>()
const emit = defineEmits<{ 'update:name': [value: string]; 'update:badge': [value: string]; pick: [officer: Officer | null] }>()

function choose(badge: string) {
  const officer = props.officers.find((item) => item.badgeNumber === badge) ?? null
  emit('update:badge', officer?.badgeNumber ?? '')
  emit('update:name', officer?.name ?? '')
  emit('pick', officer)
}
</script>

<template>
  <select
    v-if="available"
    class="officer-select"
    :value="badge"
    :disabled="disabled"
    :aria-label="ariaLabel"
    @change="choose(($event.target as HTMLSelectElement).value)"
  >
    <option value="">{{ placeholder || '请选择民警' }}</option>
    <option v-for="officer in officers" :key="officer.badgeNumber" :value="officer.badgeNumber" :disabled="officer.badgeNumber === exclude">
      {{ officer.name }}（{{ officer.badgeNumber }}）{{ officer.badgeNumber === exclude ? ' · 已担任另一角色' : '' }}
    </option>
  </select>
  <input
    v-else
    class="officer-select"
    :value="name"
    :disabled="disabled"
    :aria-label="ariaLabel"
    :placeholder="placeholder ? placeholder.replace('选择', '填写') : '填写民警姓名'"
    autocomplete="off"
    @input="emit('update:name', ($event.target as HTMLInputElement).value)"
  />
</template>
