import { computed, onMounted, ref } from 'vue'
import { fetchAuthSession, fetchOfficers, type Officer } from '../api/officers'

/**
 * 民警名录下拉的数据源：启用中的民警 + 当前登录民警。
 *
 * 名录未配置或未登录时（开发预览、尚未建名录的设备）接口不可用，`available` 为 false，
 * 页面退回手工填写姓名，不阻断建案。
 */
export function useOfficerRoster() {
  const officers = ref<Officer[]>([])
  const sessionOfficer = ref<Officer | null>(null)
  const loaded = ref(false)

  async function load() {
    const [roster, session] = await Promise.allSettled([fetchOfficers(true), fetchAuthSession()])
    officers.value = roster.status === 'fulfilled' ? roster.value.filter((item) => item.enabled) : []
    sessionOfficer.value = session.status === 'fulfilled' ? session.value.officer : null
    loaded.value = true
  }

  const available = computed(() => officers.value.length > 0)
  const byBadge = (badge: string) => officers.value.find((item) => item.badgeNumber === badge) ?? null
  /** 只有姓名时（旧案件、手工填写）按姓名在名录里找唯一一人。 */
  function byName(name: string) {
    const matches = officers.value.filter((item) => item.name === name.trim())
    return matches.length === 1 ? matches[0] : null
  }

  onMounted(load)
  return { officers, sessionOfficer, loaded, available, byBadge, byName, reload: load }
}
