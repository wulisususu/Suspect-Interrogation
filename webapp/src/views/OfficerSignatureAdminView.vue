<script setup lang="ts">
/**
 * 民警签名管理（真实功能，替代 P32 占位）
 *
 * 后端要求登录态：未配置名录时给配置指引，已配置但未验证时给登录入口。
 * 预录入签名是“个人凭证”，非管理员只能维护本人签名，服务端同样会拦（403）。
 */
import { computed, onMounted, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import SignaturePad from '../components/SignaturePad.vue'
import {
  fetchAuthSession,
  fetchOfficerSignatures,
  fetchOfficers,
  fetchSignatureUses,
  saveOfficerSignature,
  setOfficerSignatureEnabled,
  type AuthSession,
  type Officer,
  type OfficerSignature,
  type SignatureUse,
} from '../api/officers'

const emit = defineEmits<{ login: [] }>()

type Gate = 'loading' | 'unconfigured' | 'unauthenticated' | 'ready' | 'error'

const gate = ref<Gate>('loading')
const session = ref<AuthSession | null>(null)
const officers = ref<Officer[]>([])
const selected = ref<Officer | null>(null)
const signatures = ref<OfficerSignature[]>([])
const uses = ref<SignatureUse[]>([])
const loadingDetail = ref(false)
const saving = ref(false)
const error = ref('')
const message = ref('')
const enrollOpen = ref(false)
const padInk = ref(false)
const pad = ref<InstanceType<typeof SignaturePad> | null>(null)

const canManage = computed(() => {
  const actor = session.value?.officer
  if (!actor || !selected.value) return false
  return actor.isAdmin || actor.badgeNumber === selected.value.badgeNumber
})

const provisionCommand = 'python -m app.auth.provision --badge-number <警号> --name <姓名> --unit <单位> --admin'

async function boot() {
  gate.value = 'loading'
  error.value = ''
  try {
    const current = await fetchAuthSession()
    session.value = current
    if (!current.configured) {
      gate.value = 'unconfigured'
      return
    }
    if (!current.authenticated || current.locked) {
      gate.value = 'unauthenticated'
      return
    }
    gate.value = 'ready'
    await loadOfficers()
  } catch (err) {
    gate.value = 'error'
    error.value = err instanceof Error ? err.message : '民警名录读取失败'
  }
}

async function loadOfficers() {
  officers.value = await fetchOfficers(true)
  if (!selected.value && officers.value.length) await select(officers.value[0]!)
}

async function select(officer: Officer) {
  selected.value = officer
  loadingDetail.value = true
  error.value = ''
  message.value = ''
  signatures.value = []
  uses.value = []
  try {
    signatures.value = await fetchOfficerSignatures(officer.badgeNumber)
    const actor = session.value?.officer
    if (actor?.isAdmin || actor?.badgeNumber === officer.badgeNumber) {
      uses.value = await fetchSignatureUses(officer.badgeNumber)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '签名记录读取失败'
  } finally {
    loadingDetail.value = false
  }
}

async function saveSignature() {
  if (!selected.value || !canManage.value) return
  const imageData = pad.value?.toDataUrl()
  if (!imageData) {
    error.value = '请先在签名区完成手写签名'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await saveOfficerSignature(selected.value.badgeNumber, imageData)
    message.value = '签名已预录入'
    enrollOpen.value = false
    padInk.value = false
    await select(selected.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '签名保存失败'
  } finally {
    saving.value = false
  }
}

async function toggle(signature: OfficerSignature) {
  if (!canManage.value) return
  try {
    await setOfficerSignatureEnabled(signature.id, !signature.enabled)
    if (selected.value) await select(selected.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '签名状态更新失败'
  }
}

function fmt(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(boot)
</script>

<template>
  <section class="signature-admin">
    <header class="page-head">
      <div>
        <h1>民警签名管理</h1>
        <p>签名预先手写录入并绑定警号 · 签署环节由本人确认调用 · 停用后不可调用但保留记录</p>
      </div>
      <button type="button" class="ghost" @click="boot">刷新</button>
    </header>

    <p v-if="error" class="page-error" role="alert">{{ error }}</p>
    <p v-if="message" class="page-ok" role="status">{{ message }}</p>

    <section v-if="gate === 'loading'" class="page-note">正在读取民警名录…</section>

    <section v-else-if="gate === 'unconfigured'" class="page-note">
      <strong>尚未配置民警名录</strong>
      <p>签名管理需要先有民警账号。请部署人员在板端执行一次初始化（密码在终端隐藏输入，不作为参数或明文入库）：</p>
      <code>{{ provisionCommand }}</code>
    </section>

    <section v-else-if="gate === 'unauthenticated'" class="page-note">
      <strong>需要民警身份验证</strong>
      <p>签名是个人凭证，调阅与维护都必须先验证身份（验证后 10 分钟内免验）。</p>
      <button type="button" class="primary" @click="emit('login')">前往验证</button>
    </section>

    <section v-else-if="gate === 'error'" class="page-note">
      <strong>读取失败</strong>
      <p>{{ error }}</p>
      <button type="button" class="ghost" @click="boot">重试</button>
    </section>

    <div v-else class="signature-grid">
      <aside class="officer-rail" aria-label="民警名录">
        <EmptyState
          v-if="!officers.length"
          kind="empty"
          title="名录里还没有民警"
          description="由管理员在板端 provision 后再刷新。"
        />
        <button
          v-for="officer in officers"
          :key="officer.badgeNumber"
          type="button"
          :class="{ active: selected?.badgeNumber === officer.badgeNumber }"
          @click="select(officer)"
        >
          <strong>{{ officer.name }}</strong>
          <small>{{ officer.badgeNumber }} · {{ officer.unit || '未填单位' }}{{ officer.isAdmin ? ' · 管理员' : '' }}</small>
        </button>
      </aside>

      <div class="signature-main">
        <template v-if="selected">
          <header class="detail-head">
            <h2>{{ selected.name }}（{{ selected.badgeNumber }}）</h2>
            <button
              type="button"
              class="primary"
              :disabled="!canManage"
              :title="canManage ? '' : '只能维护本人的预录入签名'"
              @click="enrollOpen = true; padInk = false"
            >＋ 新增 / 更换签名</button>
          </header>

          <p v-if="!canManage" class="page-note-inline">非本人且非管理员：只能查看，不能维护该民警的签名。</p>

          <table class="data-table">
            <thead><tr><th>版本</th><th>签名样式</th><th>录入时间</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in signatures" :key="item.id">
                <td>v{{ item.version }}</td>
                <td><img :src="item.imageData" alt="预录入签名" class="signature-thumb" /></td>
                <td>{{ fmt(item.createdAt) }}</td>
                <td><span class="badge" :class="item.enabled ? 'ok' : 'warn'">{{ item.enabled ? '可调用' : '已停用' }}</span></td>
                <td>
                  <button type="button" class="link" :disabled="!canManage" @click="toggle(item)">
                    {{ item.enabled ? '停用' : '启用' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-if="!loadingDetail && !signatures.length" kind="empty" title="该民警还没有预录入签名" description="点右上角「新增 / 更换签名」手写录入。" />

          <section class="uses-block">
            <h3>调用记录（最近 50 次）</h3>
            <p v-if="!uses.length" class="page-note-inline">暂无调用记录。签名只有在民警本人确认、且被选为本案询问人/记录员时才能写入文书。</p>
            <ul v-else class="use-list">
              <li v-for="use in uses" :key="use.id">
                <span>案 {{ use.caseId }}</span>
                <span>{{ fmt(use.usedAt) }}</span>
                <small>快照 {{ use.snapshotId || '—' }}</small>
              </li>
            </ul>
          </section>
        </template>
        <EmptyState v-else kind="empty" title="先在左侧选择民警" />
      </div>
    </div>

    <div v-if="enrollOpen" class="enroll-modal" role="dialog" aria-modal="true" aria-label="新增或更换民警签名">
      <section class="enroll-dialog">
        <h2>新增 / 更换签名 · {{ selected?.name }}</h2>
        <p>警号 {{ selected?.badgeNumber }} · 保存后生成新版本，旧版本保留但停用</p>
        <SignaturePad ref="pad" @changed="padInk = $event" />
        <p v-if="!padInk" class="page-note-inline">至少写一笔才能保存。</p>
        <footer>
          <button type="button" class="ghost" :disabled="saving" @click="enrollOpen = false">取消</button>
          <button type="button" class="primary" :disabled="saving || !padInk" @click="saveSignature">
            {{ saving ? '保存中…' : '保存签名' }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.signature-admin { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.page-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.page-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-note { display: flex; flex-direction: column; gap: var(--space-2); align-items: flex-start; padding: var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); color: var(--ink-600); font-size: var(--text-sm); }
.page-note strong { color: var(--ink-900); }
.page-note p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-note code { padding: var(--space-2); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--ink-700); font-size: var(--text-xs); word-break: break-all; }
.page-note-inline { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.page-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); }
.page-ok { margin: 0; color: var(--success-700); font-size: var(--text-xs); }
.signature-grid { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.officer-rail { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-2); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
.officer-rail button { display: flex; flex-direction: column; gap: 2px; padding: var(--space-2) var(--space-3); border: 0; border-radius: var(--radius-md); background: transparent; text-align: left; cursor: pointer; }
.officer-rail button.active { background: var(--primary-50); }
.officer-rail strong { color: var(--ink-800); font-size: var(--text-sm); }
.officer-rail small { color: var(--ink-400); font-size: var(--text-xs); }
.signature-main { display: flex; flex-direction: column; gap: var(--space-3); }
.detail-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.detail-head h2 { margin: 0; color: var(--ink-900); font-size: var(--text-base); }
.data-table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--line-300); border-radius: var(--radius-lg); overflow: hidden; }
.data-table th { padding: var(--space-2) var(--space-3); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); text-align: left; }
.data-table td { padding: var(--space-2) var(--space-3); border-top: 1px solid var(--line-200); color: var(--ink-700); font-size: var(--text-sm); }
.signature-thumb { max-width: 180px; max-height: 64px; border: 1px solid var(--line-200); border-radius: var(--radius-sm); background: var(--surface); }
.badge { padding: 1px 8px; border-radius: 999px; font-size: var(--text-xs); }
.badge.ok { background: var(--success-50); color: var(--success-700); }
.badge.warn { background: var(--warning-50); color: var(--warning-700); }
.link { border: 0; background: transparent; color: var(--primary-700); font-size: var(--text-xs); cursor: pointer; }
.link:disabled { color: var(--ink-400); cursor: default; }
.uses-block { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
.uses-block h3 { margin: 0; color: var(--ink-700); font-size: var(--text-sm); }
.use-list { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.use-list li { display: grid; grid-template-columns: 1fr auto; gap: 2px var(--space-3); padding: var(--space-2); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--ink-600); font-size: var(--text-xs); }
.use-list small { grid-column: 1 / -1; color: var(--ink-400); }
.primary, .ghost { min-height: 38px; padding: 0 var(--space-4); border-radius: var(--radius-md); font-size: var(--text-sm); cursor: pointer; }
.primary { border: 0; background: var(--primary-600); color: var(--surface); }
.ghost { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.primary:disabled, .ghost:disabled { opacity: 0.6; cursor: default; }
.enroll-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--space-5); background: rgba(22, 38, 63, 0.72); }
.enroll-dialog { display: flex; flex-direction: column; gap: var(--space-3); width: min(560px, 100%); padding: var(--space-6); border-radius: var(--radius-lg); background: var(--surface); }
.enroll-dialog h2 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.enroll-dialog p { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.enroll-dialog footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
@media (max-width: 1100px) { .signature-grid { grid-template-columns: 1fr; } }
</style>
