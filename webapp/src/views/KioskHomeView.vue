<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ChevronRight, Lock, Mic, Nfc, ServerCog, ShieldCheck } from '@lucide/vue'
import { backendErrorMessage, fetchCases, fetchRuntimeCapabilities } from '../api/interrogation'
import KioskPendingBanner from '../components/KioskPendingBanner.vue'
import { branding } from '../config/branding'
import type { RuntimeCapabilities, RuntimeCapabilityName } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'
import { unfinishedCases } from '../utils/kioskLobby'

/**
 * 首页 · 一体机大厅（样板 P04）
 *
 * 办理人员进门看到的第一屏：人工模式入口、未完成办理提示（只给条数）与设备自检。
 * 嫌疑人询问不提供当事人自助模式，右栏放设备自检。案件详情属于民警验证后的管理域。
 */
const emit = defineEmits<{ start: []; policeEntry: [] }>()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const loadError = ref('')
const devices = ref<RuntimeCapabilities | null>(null)
const deviceError = ref('')
const now = ref(new Date())
let clockTimer: number | undefined

const clockText = computed(() => {
  const d = now.value
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} 周${week} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

const pendingCount = computed(() => unfinishedCases(cases.value).length)

const deviceItems = computed(() => {
  const caps = devices.value
  // 后端 reason 往往是英文驱动/SDK 信息，界面上只给结论，细节收到 title 里
  const pick = (name: RuntimeCapabilityName) => {
    if (!caps) return { ok: false, label: '检查中…', detail: '' }
    const item = caps[name]
    if (item?.state === 'AVAILABLE') return { ok: true, label: '正常', detail: '' }
    const label = item?.state === 'NOT_CONFIGURED' ? '未配置' : '未就绪'
    return { ok: false, label, detail: item?.reason || '' }
  }
  return [
    { key: 'microphone', title: '一体机麦克风', icon: Mic, ...pick('microphone') },
    { key: 'identity', title: '身份证读卡器', icon: Nfc, ...pick('identity') },
    { key: 'asr', title: '语音识别服务', icon: ServerCog, ...pick('asr') },
  ]
})
const devicesReady = computed(() => deviceItems.value.every((item) => item.ok))
const deviceSummary = computed(() => {
  if (!devices.value) return '设备：自检中'
  return devicesReady.value ? '设备：麦克风 · 读卡器 · 语音识别 就绪' : '设备：部分未就绪，可人工录入身份继续办理'
})

const flowSteps = [
  { title: '选模板建档', detail: '选择笔录模板并录入身份信息' },
  { title: '问答与定稿', detail: '民警提问实时转写，划选摘入正本' },
  { title: '签署打印', detail: '屏上签名捺印，打印件含签章装卷' },
]

async function load() {
  loading.value = true
  loadError.value = ''
  deviceError.value = ''
  try {
    cases.value = await fetchCases(50)
  } catch (cause) {
    loadError.value = backendErrorMessage(cause)
  } finally {
    loading.value = false
  }
  try {
    devices.value = await fetchRuntimeCapabilities(true)
  } catch (cause) {
    devices.value = null
    deviceError.value = backendErrorMessage(cause)
  }
}

onMounted(() => {
  void load()
  clockTimer = window.setInterval(() => { now.value = new Date() }, 30_000)
})
onUnmounted(() => {
  if (clockTimer !== undefined) window.clearInterval(clockTimer)
})
</script>

<template>
  <main class="kiosk-home">
    <header class="kiosk-topbar">
      <strong>{{ branding.productName }}</strong>
      <span v-if="branding.venueName" class="kiosk-venue">{{ branding.venueName }}</span>
      <button type="button" class="kiosk-police-entry" @click="emit('policeEntry')"><Lock :size="14" aria-hidden="true" />民警入口</button>
    </header>

    <div class="kiosk-body">
      <section class="kiosk-greeting">
        <div>
          <h1>欢迎使用公安笔录一体机</h1>
          <p>民警办案请点人工模式 · 全程保密</p>
        </div>
        <span class="kiosk-clock">{{ clockText }}</span>
      </section>

      <p v-if="loadError" class="kiosk-alert" role="alert">{{ loadError }}<button type="button" @click="load">重新检查</button></p>
      <KioskPendingBanner v-else-if="pendingCount" :count="pendingCount" @verify="emit('policeEntry')" />

      <div class="kiosk-modes">
        <section class="kiosk-card" aria-labelledby="kiosk-manual-title">
          <header class="kiosk-card-head">
            <span class="kiosk-card-icon" aria-hidden="true"><ShieldCheck :size="34" /></span>
            <div>
              <h2 id="kiosk-manual-title">人工模式 <span class="kiosk-badge">民警办理</span></h2>
              <p>民警提问、系统实时转写，左侧草稿右侧正本，划选摘入后定稿</p>
              <small>适用：民警提问录入 · 询问 / 讯问笔录办理</small>
            </div>
          </header>
          <div class="kiosk-flow">
            <span class="kiosk-flow-label">办理流程</span>
            <ol>
              <li v-for="(step, index) in flowSteps" :key="step.title">
                <b>{{ index + 1 }}</b>
                <strong>{{ step.title }}</strong>
                <span>{{ step.detail }}</span>
              </li>
            </ol>
          </div>
          <footer>
            <small>笔录生成后可导出 Word / PDF 或打印件</small>
            <button type="button" class="kiosk-primary" @click="emit('start')">开始新建笔录<ChevronRight :size="17" aria-hidden="true" /></button>
          </footer>
        </section>

        <section class="kiosk-card kiosk-devices" aria-labelledby="kiosk-device-title">
          <h2 id="kiosk-device-title">设备自检</h2>
          <ul>
            <li v-for="item in deviceItems" :key="item.key" :title="item.detail || undefined">
              <component :is="item.icon" :size="18" aria-hidden="true" />
              <span>{{ item.title }}</span>
              <em :class="{ ok: item.ok }">{{ item.label }}</em>
            </li>
          </ul>
          <p v-if="deviceError" class="kiosk-alert" role="alert">{{ deviceError }}</p>
          <button type="button" class="kiosk-secondary" @click="load">重新自检</button>
        </section>
      </div>

      <section class="kiosk-strip" aria-label="办理须知">
        <span><i class="dot is-primary" aria-hidden="true"></i>合规：民警在场确认后定稿</span>
        <span><i class="dot is-success" aria-hidden="true"></i>隐私：全程保密，仅用于本次办理</span>
        <span><i class="dot" :class="devicesReady ? 'is-success' : 'is-warning'" aria-hidden="true"></i>{{ deviceSummary }}</span>
      </section>
    </div>

    <footer class="kiosk-footer">
      <span>{{ [branding.unitName, branding.venueName, '值班民警在场'].filter(Boolean).join(' · ') }}</span>
      <span>使用中有疑问，请呼叫在场民警</span>
    </footer>
  </main>
</template>

<style scoped>
.kiosk-home { display: flex; flex-direction: column; height: 100vh; overflow: auto; background: var(--surface-sunken); }

.kiosk-topbar { display: flex; align-items: center; gap: var(--space-3); flex: 0 0 auto; min-height: var(--height-topbar); padding: 0 var(--space-8); background: var(--navy-900); color: var(--surface); }
.kiosk-topbar strong { font-size: var(--text-lg); font-weight: 600; letter-spacing: 0.5px; }
.kiosk-venue { padding: 3px 10px; border-radius: var(--radius-pill); background: rgba(255, 255, 255, 0.1); color: var(--primary-100); font-size: var(--text-xs); }
.kiosk-police-entry { display: inline-flex; align-items: center; gap: var(--space-1); margin-left: auto; min-height: 36px; padding: 0 var(--space-4); border: 1px solid rgba(255, 255, 255, 0.24); border-radius: var(--radius-sm); background: rgba(255, 255, 255, 0.08); color: var(--primary-100); font-size: var(--text-sm); }
.kiosk-police-entry:hover { background: rgba(255, 255, 255, 0.16); }

.kiosk-body { flex: 1 1 auto; width: 100%; max-width: 1320px; margin: 0 auto; padding: var(--space-8) var(--space-8) var(--space-6); display: flex; flex-direction: column; gap: var(--space-5); }

.kiosk-greeting { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-6); }
.kiosk-greeting h1 { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 650; }
.kiosk-greeting p { margin: var(--space-2) 0 0; color: var(--ink-500); font-size: var(--text-md); }
.kiosk-clock { padding: var(--space-1) var(--space-3); border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-xs); font-variant-numeric: tabular-nums; white-space: nowrap; }

.kiosk-alert { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin: 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--danger-100); color: var(--danger-700); font-size: var(--text-sm); }
.kiosk-alert button { min-height: 36px; padding: 0 var(--space-3); border: 1px solid var(--danger-600); border-radius: var(--radius-sm); background: var(--surface); color: var(--danger-700); }

.kiosk-modes { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-5); }
.kiosk-card { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-6); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-card); }
.kiosk-modes > .kiosk-card:first-child { border-color: var(--primary-500); background: var(--primary-50); }
.kiosk-card-head { display: flex; gap: var(--space-4); }
.kiosk-card-icon { display: grid; place-items: center; width: 72px; height: 72px; flex: none; border-radius: var(--radius-lg); background: var(--primary-100); color: var(--primary-600); }
.kiosk-card h2 { display: flex; align-items: center; gap: var(--space-2); margin: 0 0 var(--space-2); color: var(--ink-900); font-size: var(--text-2xl); font-weight: 650; }
.kiosk-badge { padding: 3px 10px; border-radius: var(--radius-pill); background: var(--primary-600); color: var(--surface); font-size: var(--text-xs); font-weight: 600; }
.kiosk-card-head p { margin: 0 0 var(--space-2); color: var(--ink-700); font-size: var(--text-base); }
.kiosk-card-head small, .kiosk-card footer small { color: var(--ink-400); font-size: var(--text-xs); }

.kiosk-flow { padding: var(--space-4); border-radius: var(--radius-md); background: var(--surface-muted); }
.kiosk-flow-label { color: var(--ink-400); font-size: var(--text-xs); }
.kiosk-flow ol { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); margin: var(--space-3) 0 0; padding: 0; list-style: none; }
.kiosk-flow li { display: flex; flex-direction: column; gap: var(--space-1); }
.kiosk-flow b { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: var(--primary-600); color: var(--surface); font-size: var(--text-xs); }
.kiosk-flow strong { color: var(--primary-600); font-size: var(--text-base); font-weight: 600; }
.kiosk-flow span { color: var(--ink-500); font-size: var(--text-xs); }

.kiosk-card footer { display: flex; flex-direction: column; gap: var(--space-2); margin-top: auto; }
.kiosk-primary { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 48px; border: 0; border-radius: var(--radius-md); background: var(--primary-600); color: var(--surface); font-size: var(--text-md); font-weight: 600; }
.kiosk-primary:hover { background: var(--primary-700); }

.kiosk-devices h2 { font-size: var(--text-xl); }
.kiosk-devices ul { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.kiosk-devices li { display: flex; align-items: center; gap: var(--space-3); min-height: 52px; padding: 0 var(--space-4); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--ink-700); font-size: var(--text-base); }
.kiosk-devices li em { margin-left: auto; color: var(--warning-700); font-style: normal; font-weight: 600; }
.kiosk-devices li em.ok { color: var(--success-700); }
.kiosk-secondary { min-height: 44px; margin-top: auto; border: 1px solid var(--primary-500); border-radius: var(--radius-md); background: var(--surface); color: var(--primary-600); font-size: var(--text-base); font-weight: 600; }

.kiosk-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-4); padding: var(--space-4) var(--space-5); border-radius: var(--radius-md); background: var(--surface-muted); color: var(--ink-700); font-size: var(--text-sm); }
.kiosk-strip span { display: flex; align-items: center; gap: var(--space-2); }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.dot.is-primary { background: var(--primary-600); }
.dot.is-success { background: var(--success-600); }
.dot.is-warning { background: var(--warning-600); }

.kiosk-footer { display: flex; justify-content: space-between; gap: var(--space-4); padding: var(--space-3) var(--space-8); border-top: 1px solid var(--line-200); background: var(--surface); color: var(--ink-400); font-size: var(--text-xs); }

@media (max-width: 1100px) {
  .kiosk-modes, .kiosk-strip { grid-template-columns: 1fr; }
}
</style>
