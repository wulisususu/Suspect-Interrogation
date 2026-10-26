<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ArrowRight, FilePenLine, Mic, Nfc, ServerCog } from '@lucide/vue'
import { backendErrorMessage, fetchCases, fetchRuntimeCapabilities } from '../api/interrogation'
import type { RuntimeCapabilities, RuntimeCapabilityName } from '../runtime/types'
import type { CaseSummary } from '../types/interrogation'

/**
 * 一体机大厅
 *
 * 办理人员进门看到的第一屏：先确认设备可用、有没有做到一半的案子，
 * 再决定是继续办理还是新建。案件台账不在这里展开——那是民警验证后的管理域。
 */
const emit = defineEmits<{ start: []; resume: [caseId: string]; policeEntry: [] }>()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const loadError = ref('')
const devices = ref<RuntimeCapabilities | null>(null)
const deviceError = ref('')
const now = ref(new Date())
let clockTimer: number | undefined

const clock = computed(() => {
  const d = now.value
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return {
    date: `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`,
    time: `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`,
    week: `星期${week}`,
  }
})

function unfinished(item: CaseSummary) {
  const workflow = item.workflowState || ''
  return workflow !== 'REPORT_GENERATED' && item.state !== 'ARCHIVED'
}
const pendingCases = computed(() => cases.value.filter(unfinished))
const todayCount = computed(() => {
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  return cases.value.filter((item) => (item.createdAt || 0) >= start.getTime()).length
})

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
    { key: 'identity', title: '身份证读卡器', icon: Nfc, ...pick('identity') },
    { key: 'microphone', title: '一体机麦克风', icon: Mic, ...pick('microphone') },
    { key: 'asr', title: '语音识别服务', icon: ServerCog, ...pick('asr') },
  ]
})
const devicesReady = computed(() => deviceItems.value.every((item) => item.ok))

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
      <span class="kiosk-brand-mark" aria-hidden="true">★</span>
      <strong>公安笔录智能工作台</strong>
      <span class="kiosk-venue">一楼办理大厅</span>
      <button type="button" class="kiosk-police-entry" @click="emit('policeEntry')">民警入口</button>
    </header>

    <div class="kiosk-body">
      <section class="kiosk-greeting">
        <div>
          <h1>欢迎使用公安笔录一体机</h1>
          <p>按屏幕提示完成身份核对与问答，全程由在场民警核实</p>
        </div>
        <div class="kiosk-clock">
          <strong>{{ clock.time }}</strong>
          <span>{{ clock.date }} · {{ clock.week }}</span>
        </div>
      </section>

      <p v-if="loadError" class="kiosk-alert" role="alert">{{ loadError }}<button type="button" @click="load">重新检查</button></p>
      <button v-else-if="pendingCases.length" type="button" class="kiosk-pending" @click="emit('resume', pendingCases[0]!.id)">
        <span class="kiosk-pending-count">{{ pendingCases.length }}</span>
        <span class="kiosk-pending-text">项未完成办理 · 含断电恢复与挂起会话，验证后展开详情</span>
        <span class="kiosk-pending-action">继续办理<ArrowRight :size="16" /></span>
      </button>
      <p v-else-if="!loading" class="kiosk-clear">当前没有未完成的笔录，可新建一起</p>

      <section class="kiosk-card" aria-labelledby="kiosk-entry-title">
        <header>
          <span class="kiosk-card-kicker">人工模式 · 民警办理</span>
          <h2 id="kiosk-entry-title">新建一份询问笔录</h2>
          <p>选模板 → 建档核对 → 问答成文 → 定稿校验 → 签署归档，一条线走完</p>
        </header>
        <ol class="kiosk-steps">
          <li><b>①</b><span>选模板建档</span></li>
          <li><b>②</b><span>问答与定稿</span></li>
          <li><b>③</b><span>签署并归档</span></li>
        </ol>
        <footer>
          <p class="kiosk-today">今日已建 {{ todayCount }} 起</p>
          <button type="button" class="kiosk-primary" @click="emit('start')">
            <FilePenLine :size="18" />开始新建笔录
          </button>
        </footer>
      </section>

      <section class="kiosk-devices" aria-label="设备自检">
        <div v-for="item in deviceItems" :key="item.key" class="kiosk-device">
          <span class="kiosk-device-dot" :class="{ ok: item.ok }" aria-hidden="true"></span>
          <component :is="item.icon" :size="15" aria-hidden="true" />
          <span :title="item.detail || undefined">{{ item.title }} · {{ item.label }}</span>
        </div>
        <button type="button" class="kiosk-device-refresh" @click="load">重新自检</button>
      </section>
      <p v-if="deviceError" class="kiosk-alert" role="alert">{{ deviceError }}</p>

      <footer class="kiosk-footer">
        <span>{{ devicesReady ? '设备就绪，可以开始办理' : '部分设备未就绪，仍可人工录入身份继续办理' }}</span>
        <span class="kiosk-footer-note">内网专用终端 · 全程留痕 · 笔录签字捺印后生效</span>
      </footer>
    </div>
  </main>
</template>

<style scoped>
.kiosk-home {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: auto;
  background: var(--surface-sunken);
}

.kiosk-topbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 0 0 auto;
  min-height: var(--height-topbar);
  padding: 0 var(--space-8);
  background: var(--navy-900);
  color: var(--surface);
}
.kiosk-brand-mark { color: var(--warning-700); font-size: var(--text-md); }
.kiosk-topbar strong { font-size: var(--text-lg); font-weight: 600; letter-spacing: 0.5px; }
.kiosk-venue {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.1);
  color: var(--primary-100);
  font-size: var(--text-sm);
}
.kiosk-police-entry {
  margin-left: auto;
  min-height: 34px;
  padding: 0 16px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--primary-100);
  font-size: var(--text-sm);
}
.kiosk-police-entry:hover { background: rgba(255, 255, 255, 0.12); }

.kiosk-body {
  flex: 1 1 auto;
  width: 100%;
  max-width: 1240px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-8) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.kiosk-greeting { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-6); }
.kiosk-greeting h1 { margin: 0; color: var(--ink-900); font-size: var(--text-3xl); font-weight: 600; letter-spacing: 0.5px; }
.kiosk-greeting p { margin: var(--space-2) 0 0; color: var(--ink-500); font-size: var(--text-md); }
.kiosk-clock { text-align: right; }
.kiosk-clock strong { display: block; color: var(--primary-700); font-size: 40px; /* token-exempt: 大厅时钟读数 */ font-weight: 600; line-height: 1; font-variant-numeric: tabular-nums; }
.kiosk-clock span { color: var(--ink-400); font-size: var(--text-sm); }

.kiosk-pending {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--warning-700);
  border-radius: var(--radius-md);
  background: var(--warning-100);
  color: var(--warning-700);
  text-align: left;
  font-size: var(--text-base);
}
.kiosk-pending:hover { border-color: var(--warning-700); }
.kiosk-pending-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 24px;
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--warning-700);
  font-weight: 600;
}
.kiosk-pending-text { flex: 1 1 auto; min-width: 0; }
.kiosk-pending-action { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; white-space: nowrap; }
.kiosk-clear { margin: 0; padding: var(--space-2) 0; color: var(--ink-400); font-size: var(--text-base); }

.kiosk-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-7);
  border: 1px solid var(--line-200);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-card);
}
.kiosk-card-kicker { color: var(--primary-600); font-size: var(--text-sm); font-weight: 600; }
.kiosk-card h2 { margin: var(--space-2) 0 var(--space-1); color: var(--ink-900); font-size: var(--text-2xl); font-weight: 600; }
.kiosk-card header p { margin: 0; color: var(--ink-500); font-size: var(--text-base); }

.kiosk-steps { display: flex; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.kiosk-steps li {
  flex: 1 1 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--primary-50);
  color: var(--ink-700);
  font-size: var(--text-base);
}
.kiosk-steps b { color: var(--primary-600); font-size: var(--text-md); }

.kiosk-card footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); }
.kiosk-today { margin: 0; color: var(--ink-400); font-size: var(--text-sm); }
.kiosk-primary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 52px;
  padding: 0 var(--space-7);
  border: 0;
  border-radius: var(--radius-md);
  background: var(--primary-600);
  color: var(--surface);
  font-size: var(--text-md);
  font-weight: 600;
}
.kiosk-primary:hover { background: var(--primary-700); }

.kiosk-devices {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--line-200);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--ink-500);
  font-size: var(--text-sm);
}
.kiosk-device { display: inline-flex; align-items: center; gap: var(--space-2); }
.kiosk-device-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ink-300); }
.kiosk-device-dot.ok { background: var(--success-600); }
.kiosk-device-refresh {
  margin-left: auto;
  min-height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line-300);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--primary-600);
  font-size: var(--text-sm);
}

.kiosk-alert {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--danger-100);
  color: var(--danger-700);
  font-size: var(--text-base);
}
.kiosk-alert button {
  margin-left: auto;
  min-height: 30px;
  padding: 0 12px;
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  background: transparent;
  color: inherit;
  font-size: var(--text-sm);
}

.kiosk-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: auto;
  padding-top: var(--space-3);
  border-top: 1px solid var(--line-200);
  color: var(--ink-400);
  font-size: var(--text-sm);
}
.kiosk-footer-note { color: var(--ink-300); }

@media (max-width: 900px) {
  .kiosk-body { padding: var(--space-5); }
  .kiosk-greeting h1 { font-size: var(--text-2xl); }
  .kiosk-clock strong { font-size: var(--text-3xl); }
  .kiosk-steps { flex-direction: column; }
}
</style>
