<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ChevronRight, Lock, Mic, Nfc, ServerCog, ShieldCheck, UserRoundCheck } from '@lucide/vue'
import { backendErrorMessage, fetchCases, fetchRuntimeCapabilities } from '../api/interrogation'
import KioskPendingBanner from '../components/KioskPendingBanner.vue'
import { branding } from '../config/branding'
import type { RuntimeCapabilities, RuntimeCapabilityName } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'
import { unfinishedCases } from '../utils/kioskLobby'
import type { LoginTarget } from '../utils/rootRoute'

/**
 * 首页 · 一体机大厅（样板 P04）
 *
 * 进门看到的第一屏：左人工模式（民警提问录入）、右自助模式（当事人本人作答），
 * 两种模式都要民警先验证身份，登录当天有效。未完成办理只给条数，设备自检收在底部状态条。
 * 案件详情属于民警验证后的管理域。
 */
const emit = defineEmits<{ enter: [target: LoginTarget] }>()

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
  { title: '选模板建档', detail: '读取身份证建案，选择笔录模板后补全身份信息' },
  { title: '问答与定稿', detail: '民警提问实时转写，划选摘入正本' },
  { title: '签署打印', detail: '屏上签名捺印，打印件含签章装卷' },
]
const selfSteps = [
  { title: '民警建档', detail: '民警读卡建案、选好模板，再把屏幕交给本人' },
  { title: '本人作答', detail: '本人核对身份，对照屏幕逐题口述回答' },
  { title: '民警定稿', detail: '在场民警核对摘入正本，签署打印' },
]

async function load() {
  loading.value = true
  loadError.value = ''
  deviceError.value = ''
  try {
    cases.value = await fetchCases(50)
  } catch (cause) {
    // 未登录时案件列表本就不可读：大厅照常显示，民警点任一模式登录即可
    const code = (cause as { code?: string } | null)?.code
    if (code !== 'AUTH_SESSION_REQUIRED' && code !== 'AUTH_SESSION_LOCKED') loadError.value = backendErrorMessage(cause)
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
      <button type="button" class="kiosk-police-entry" @click="emit('enter', 'admin')"><Lock :size="14" aria-hidden="true" />管理面板</button>
    </header>

    <div class="kiosk-body">
      <section class="kiosk-greeting">
        <div>
          <h1>欢迎使用公安笔录一体机</h1>
          <p>民警提问请选人工模式，本人自述请选自助模式 · 全程保密</p>
        </div>
        <span class="kiosk-clock">{{ clockText }}</span>
      </section>

      <p v-if="loadError" class="kiosk-alert" role="alert">{{ loadError }}<button type="button" @click="load">重新检查</button></p>
      <KioskPendingBanner v-else-if="pendingCount" :count="pendingCount" @verify="emit('enter', 'admin')" />

      <div class="kiosk-modes">
        <section class="kiosk-card" aria-labelledby="kiosk-manual-title">
          <header class="kiosk-card-head">
            <span class="kiosk-card-icon" aria-hidden="true"><ShieldCheck :size="52" /></span>
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
            <small>需民警验证身份 · 登录当天有效</small>
            <button type="button" class="kiosk-primary" @click="emit('enter', 'manual')">开始新建笔录<ChevronRight :size="17" aria-hidden="true" /></button>
          </footer>
        </section>

        <section class="kiosk-card kiosk-card-self" aria-labelledby="kiosk-self-title">
          <header class="kiosk-card-head">
            <span class="kiosk-card-icon" aria-hidden="true"><UserRoundCheck :size="52" /></span>
            <div>
              <h2 id="kiosk-self-title">自助模式 <span class="kiosk-badge">本人作答</span></h2>
              <p>当事人对照屏幕逐题口述回答，系统录音转写，民警全程在场核对定稿</p>
              <small>适用：报案人 / 被害人 / 证人自述 · 民警全程在场</small>
            </div>
          </header>
          <div class="kiosk-flow">
            <span class="kiosk-flow-label">办理流程</span>
            <ol>
              <li v-for="(step, index) in selfSteps" :key="step.title">
                <b>{{ index + 1 }}</b>
                <strong>{{ step.title }}</strong>
                <span>{{ step.detail }}</span>
              </li>
            </ol>
          </div>
          <footer>
            <small>需民警验证身份并建档后，再交由本人作答</small>
            <button type="button" class="kiosk-primary" @click="emit('enter', 'self')">进入自助模式<ChevronRight :size="17" aria-hidden="true" /></button>
          </footer>
        </section>
      </div>

      <section class="kiosk-strip" aria-label="办理须知">
        <span><i class="dot is-primary" aria-hidden="true"></i>合规：民警在场确认后定稿</span>
        <span><i class="dot is-success" aria-hidden="true"></i>隐私：全程保密，仅用于本次办理</span>
        <span class="kiosk-strip-devices" :title="deviceItems.map((item) => `${item.title}：${item.label}${item.detail ? `（${item.detail}）` : ''}`).join('\n')">
          <i class="dot" :class="devicesReady ? 'is-success' : 'is-warning'" aria-hidden="true"></i>{{ deviceSummary }}
          <button type="button" class="kiosk-recheck" @click="load">重新自检</button>
        </span>
      </section>
      <p v-if="deviceError" class="kiosk-alert" role="alert">{{ deviceError }}</p>
      <ul v-else-if="devices && !devicesReady" class="kiosk-device-faults">
        <li v-for="item in deviceItems.filter((entry) => !entry.ok)" :key="item.key" :title="item.detail || undefined">
          <component :is="item.icon" :size="16" aria-hidden="true" />{{ item.title }}<em>{{ item.label }}</em>
        </li>
      </ul>
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

/* 样板 P04：内容左右约 48px，标题与两张模式卡片占据主要屏幕 */
.kiosk-body { flex: 1 1 auto; min-height: 0; width: 100%; padding: var(--space-10) var(--space-12) var(--space-6); display: flex; flex-direction: column; gap: var(--space-6); }

.kiosk-greeting { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-6); }
.kiosk-greeting h1 { margin: 0; color: var(--ink-900); font-size: var(--text-display); font-weight: 650; line-height: 1.2; }
.kiosk-greeting p { margin: var(--space-3) 0 0; color: var(--ink-500); font-size: var(--text-xl); }
.kiosk-clock { padding: var(--space-2) var(--space-4); border-radius: var(--radius-pill); background: var(--surface-muted); color: var(--ink-500); font-size: var(--text-md); font-variant-numeric: tabular-nums; white-space: nowrap; }

.kiosk-alert { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin: 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--danger-100); color: var(--danger-700); font-size: var(--text-sm); }
.kiosk-alert button { min-height: 36px; padding: 0 var(--space-3); border: 1px solid var(--danger-600); border-radius: var(--radius-sm); background: var(--surface); color: var(--danger-700); }

.kiosk-modes { display: grid; flex: 1 1 auto; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-8); min-height: 0; }
.kiosk-card { display: flex; flex-direction: column; gap: var(--space-8); padding: var(--space-8); border: 1px solid var(--line-200); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow-card); }
.kiosk-modes > .kiosk-card:first-child { border-color: var(--primary-500); background: var(--primary-50); }
.kiosk-card-self .kiosk-card-icon { background: var(--success-100); color: var(--success-700); }
.kiosk-card-self .kiosk-badge { background: var(--success-700); }
.kiosk-card-self .kiosk-flow b { background: var(--success-700); }
.kiosk-card-self .kiosk-flow strong { color: var(--success-700); }
.kiosk-card-head { display: flex; gap: var(--space-4); }
.kiosk-card-icon { display: grid; place-items: center; width: 108px; height: 108px; flex: none; border-radius: var(--radius-lg); background: var(--primary-100); color: var(--primary-600); }
.kiosk-card h2 { display: flex; align-items: center; gap: var(--space-3); margin: 0 0 var(--space-3); color: var(--ink-900); font-size: var(--text-4xl); font-weight: 650; }
.kiosk-badge { padding: var(--space-1) var(--space-3); border-radius: var(--radius-pill); background: var(--primary-600); color: var(--surface); font-size: var(--text-md); font-weight: 600; }
.kiosk-card-head p { margin: 0 0 var(--space-3); color: var(--ink-700); font-size: var(--text-xl); }
.kiosk-card-head small, .kiosk-card footer small { color: var(--ink-400); font-size: var(--text-md); }

.kiosk-flow { padding: var(--space-6) var(--space-8); border-radius: var(--radius-md); background: var(--surface-muted); }
.kiosk-flow-label { color: var(--ink-400); font-size: var(--text-md); }
.kiosk-flow ol { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-4); margin: var(--space-4) 0 0; padding: 0; list-style: none; }
.kiosk-flow li { display: flex; flex-direction: column; gap: var(--space-2); }
.kiosk-flow b { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; background: var(--primary-600); color: var(--surface); font-size: var(--text-md); }
.kiosk-flow strong { color: var(--primary-600); font-size: var(--text-xl); font-weight: 600; }
.kiosk-flow span { color: var(--ink-500); font-size: var(--text-md); }

.kiosk-card footer { display: flex; flex-direction: column; gap: var(--space-2); margin-top: auto; }
.kiosk-primary { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 60px; border: 0; border-radius: var(--radius-md); background: var(--primary-600); color: var(--surface); font-size: var(--text-xl); font-weight: 600; box-shadow: var(--shadow-active); }
.kiosk-primary:hover { background: var(--primary-700); }

.kiosk-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-4); padding: var(--space-5) var(--space-8); border-radius: var(--radius-md); background: var(--surface-muted); color: var(--ink-700); font-size: var(--text-lg); }
.kiosk-strip span { display: flex; align-items: center; gap: var(--space-2); }
.kiosk-recheck { margin-left: auto; min-height: 36px; padding: 0 var(--space-3); border: 1px solid var(--primary-500); border-radius: var(--radius-sm); background: var(--surface); color: var(--primary-600); font-size: var(--text-sm); font-weight: 600; white-space: nowrap; }
.kiosk-device-faults { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: calc(var(--space-4) * -1) 0 0; padding: 0; list-style: none; }
.kiosk-device-faults li { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 36px; padding: 0 var(--space-3); border-radius: var(--radius-pill); background: var(--warning-100); color: var(--warning-700); font-size: var(--text-sm); }
.kiosk-device-faults em { font-style: normal; font-weight: 600; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.dot.is-primary { background: var(--primary-600); }
.dot.is-success { background: var(--success-600); }
.dot.is-warning { background: var(--warning-600); }

.kiosk-footer { display: flex; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-12); border-top: 1px solid var(--line-200); background: var(--surface); color: var(--ink-400); font-size: var(--text-md); }

@media (max-width: 1100px) {
  .kiosk-modes, .kiosk-strip { grid-template-columns: 1fr; }
}

/* 矮屏（1366×768 扣浏览器、或 90% 缩放后只剩 500px 上下）：流程说明与底部提示属于
   辅助信息，优先保证两张模式卡与「开始」按钮留在首屏，不出现滚动条。 */
@media (max-height: 640px) {
  .kiosk-home { overflow: hidden; }
  /* 1100px 以下的宽度断点会把两张卡改成一列；矮屏时竖排必然放不下，
     这里强制恢复并排，宁可窄一点也不让第二张卡被切掉。 */
  .kiosk-modes { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 6px; }
  .kiosk-body { padding: 6px 8px 4px; gap: 6px; }
  .kiosk-greeting h1 { font-size: 24px; }
  .kiosk-greeting p { display: none; }
  .kiosk-card { gap: var(--space-3); padding: var(--space-3) var(--space-4); }
  .kiosk-card-head h2 { font-size: var(--text-lg); }
  .kiosk-flow, .kiosk-strip { display: none; }
  .kiosk-primary { min-height: 46px; font-size: var(--text-lg); }
}
</style>
