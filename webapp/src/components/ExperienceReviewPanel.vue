<script setup lang="ts">
/**
 * 经验审核（Task 02：已结案案件的经验提炼与审核入库）
 *
 * 打开时先扫描已结案案件：民警在问话中自己补充、知识库里还没有的问法，规则脱敏后成为候选。
 * 审核人核对脱敏、改写成通用问法、选好要素后「通过并发布」，写进该模板的「办案经验问法」条目
 * （新版本），下一个同类案件即可推荐；「驳回」的问法以后再出现也不再进待审核。
 * 上方另列各模板结案时仍未确认的要素，提示哪些地方容易漏问。
 */
import { computed, onMounted, ref } from 'vue'
import EmptyState from './EmptyState.vue'
import {
  approveExperience,
  fetchExperience,
  harvestExperience,
  rejectExperience,
  type ExperienceCandidate,
  type ExperienceOverview,
  type ExperienceStatus,
} from '../api/knowledge'

const emit = defineEmits<{ published: [entryId: string] }>()

const STATUS_LABELS: Record<ExperienceStatus, string> = { PENDING: '待审核', APPROVED: '已发布', REJECTED: '已驳回' }

const status = ref<ExperienceStatus>('PENDING')
const overview = ref<ExperienceOverview | null>(null)
const selectedId = ref<string | null>(null)
const form = ref({ text: '', elementKey: '', note: '' })
const busy = ref(false)
const message = ref('')
const error = ref('')

const candidates = computed(() => overview.value?.candidates ?? [])
const selected = computed(() => candidates.value.find((item) => item.id === selectedId.value) ?? null)
const scopeElements = computed(() => overview.value?.scopes.find((scope) => scope.scopeKey === selected.value?.scopeKey)?.elements ?? [])
const scopesWithGaps = computed(() => (overview.value?.scopes ?? []).filter((scope) => scope.closedCases > 0))

function select(item: ExperienceCandidate) {
  selectedId.value = item.id
  form.value = { text: item.publishedText || item.proposedText, elementKey: item.elementKey || '', note: item.reviewNote || '' }
  error.value = ''
}

async function load() {
  overview.value = await fetchExperience(status.value)
  if (!candidates.value.some((item) => item.id === selectedId.value)) {
    const first = candidates.value[0]
    if (first) select(first)
    else selectedId.value = null
  }
}

async function refresh(harvest = false) {
  busy.value = true
  error.value = ''
  try {
    if (harvest) {
      const result = await harvestExperience()
      message.value = result.newCandidates
        ? `已扫描 ${result.scannedCases} 个已结案案件，新增 ${result.newCandidates} 条候选问法`
        : `已扫描 ${result.scannedCases} 个已结案案件，没有新的候选问法`
    }
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '经验候选读取失败'
  } finally {
    busy.value = false
  }
}

async function switchStatus(next: ExperienceStatus) {
  status.value = next
  selectedId.value = null
  await refresh()
}

async function approve() {
  const item = selected.value
  if (!item || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await approveExperience(item.id, {
      text: form.value.text.trim(), elementKey: form.value.elementKey || null, note: form.value.note.trim() || undefined,
    })
    message.value = `已发布到「${result.entry.title}」v${result.entry.version}，下一个同类案件即可推荐`
    emit('published', result.entry.id)
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '发布失败'
  } finally {
    busy.value = false
  }
}

async function reject() {
  const item = selected.value
  if (!item || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await rejectExperience(item.id, form.value.note.trim() || undefined)
    message.value = '已驳回，相同问法以后不再进入待审核'
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '驳回失败'
  } finally {
    busy.value = false
  }
}

onMounted(() => { void refresh(true) })
</script>

<template>
  <section class="experience" aria-label="经验审核">
    <p class="experience-note">
      从已结案案件中，取民警问话时自己补充、知识库里还没有的问题；人名、车牌、证件号、电话、日期时刻、金额、门牌号已按规则替换，
      仍请逐条核对并改写成通用问法。只有审核通过的才发布到知识库，问法只作提示，由民警决定是否采用。
    </p>

    <div v-if="scopesWithGaps.length" class="experience-gaps">
      <article v-for="scope in scopesWithGaps" :key="scope.scopeKey">
        <header><strong>{{ scope.title }}</strong><span>已结案 {{ scope.closedCases }} 件</span></header>
        <template v-if="scope.gaps.length">
          <p>结案时仍未确认的要素（件数 / 已结案）：</p>
          <ul class="experience-gap-chips">
            <li v-for="gap in scope.gaps" :key="gap.elementKey">{{ gap.label }} <strong>{{ gap.cases }}/{{ scope.closedCases }}</strong></li>
          </ul>
        </template>
        <p v-else class="muted">结案时要素都已确认</p>
      </article>
    </div>

    <div class="experience-toolbar">
      <nav aria-label="审核状态">
        <button
          v-for="(label, key) in STATUS_LABELS"
          :key="key"
          type="button"
          :class="{ active: status === key }"
          @click="switchStatus(key)"
        >{{ label }}<span v-if="overview">{{ overview.counts[key] }}</span></button>
      </nav>
      <button type="button" class="ghost" :disabled="busy" @click="refresh(true)">{{ busy ? '处理中…' : '重新扫描已结案案件' }}</button>
    </div>

    <p v-if="message" class="experience-message" role="status">{{ message }}</p>
    <p v-if="error" class="experience-error" role="alert">{{ error }}</p>

    <EmptyState
      v-if="overview && !candidates.length"
      kind="empty"
      :title="status === 'PENDING' ? '没有待审核的经验' : `没有${STATUS_LABELS[status]}的问法`"
      description="案件冻结或签名后，民警补充的问题会出现在这里。"
    />
    <div v-else-if="candidates.length" class="experience-body">
      <ul class="experience-list">
        <li v-for="item in candidates" :key="item.id">
          <button type="button" :class="{ active: item.id === selectedId }" @click="select(item)">
            <strong>{{ item.publishedText || item.proposedText }}</strong>
            <small>
              {{ item.scopeTitle }}<template v-if="item.elementLabel"> · {{ item.elementLabel }}</template>
              · {{ item.caseCount }} 个案件补问过
              <template v-if="item.maskRules.length"> · 已替换{{ item.maskRules.join('、') }}</template>
            </small>
          </button>
        </li>
      </ul>

      <aside v-if="selected" class="experience-detail" aria-label="候选详情">
        <h3>来源问题（原文，仅供核对）</h3>
        <ul class="experience-sources">
          <li v-for="source in selected.sources" :key="source.questionId">{{ source.originalText }}</li>
        </ul>

        <template v-if="selected.status === 'APPROVED'">
          <p class="experience-meta">已发布为「{{ selected.publishedText }}」<template v-if="selected.publishedVersion"> · 条目 v{{ selected.publishedVersion }}</template><template v-if="selected.reviewedBy"> · 审核人 {{ selected.reviewedBy }}</template></p>
          <p v-if="selected.reviewNote" class="experience-meta">备注：{{ selected.reviewNote }}</p>
        </template>
        <template v-else>
          <label>
            发布的问法（通用、中立，不含具体人名地名）
            <textarea v-model="form.text" rows="3" maxlength="120" />
          </label>
          <label>
            对应要素
            <select v-model="form.elementKey">
              <option value="">不指定（按问话内容匹配）</option>
              <option v-for="element in scopeElements" :key="element.key" :value="element.key">{{ element.label }}</option>
            </select>
          </label>
          <label>
            审核备注
            <input v-model="form.note" maxlength="300" placeholder="可选，如 改写了称呼" />
          </label>
          <p v-if="selected.status === 'REJECTED'" class="experience-meta">已驳回<template v-if="selected.reviewNote">：{{ selected.reviewNote }}</template>；如判断有误，可改后发布。</p>
          <div class="experience-actions">
            <button v-if="selected.status === 'PENDING'" type="button" class="ghost" :disabled="busy" @click="reject">驳回</button>
            <button type="button" class="primary" :disabled="busy || form.text.trim().length < 4" @click="approve">通过并发布</button>
          </div>
        </template>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.experience { display: flex; flex-direction: column; gap: var(--space-3); }
.experience-note { margin: 0; color: var(--ink-500); font-size: var(--text-xs); line-height: 1.6; }
.experience-gaps { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: var(--space-2); }
.experience-gaps article { padding: var(--space-2) var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); }
.experience-gaps header { display: flex; justify-content: space-between; gap: var(--space-2); color: var(--ink-800); font-size: var(--text-sm); }
.experience-gaps header span { color: var(--ink-400); font-size: var(--text-xs); }
.experience-gaps p { margin: 4px 0 0; color: var(--warning-700); font-size: var(--text-xs); }
.experience-gaps p.muted { color: var(--ink-400); }
.experience-gap-chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0 0; padding: 0; list-style: none; }
.experience-gap-chips li { padding: 1px 8px; border-radius: 999px; background: var(--surface-sunken); color: var(--warning-700); font-size: var(--text-xs); }
.experience-gap-chips strong { font-weight: 600; }
.experience-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.experience-toolbar nav { display: flex; gap: var(--space-1); }
.experience-toolbar nav button { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: 999px; background: var(--surface); color: var(--ink-600); font-size: var(--text-xs); cursor: pointer; }
.experience-toolbar nav button.active { border-color: var(--primary-200); background: var(--primary-50); color: var(--primary-700); font-weight: 600; }
.experience-toolbar nav span { color: var(--ink-400); }
.experience-message { margin: 0; color: var(--success-700); font-size: var(--text-xs); }
.experience-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); }
.experience-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 420px); gap: var(--space-4); align-items: start; }
.experience-list { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.experience-list button { display: flex; flex-direction: column; gap: 2px; width: 100%; padding: var(--space-2) var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); text-align: left; cursor: pointer; }
.experience-list button.active { border-color: var(--primary-200); background: var(--primary-50); }
.experience-list strong { color: var(--ink-800); font-size: var(--text-sm); font-weight: 600; }
.experience-list small { color: var(--ink-400); font-size: var(--text-xs); }
.experience-detail { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
.experience-detail h3 { margin: 0; color: var(--ink-600); font-size: var(--text-xs); }
.experience-sources { margin: 0; padding: var(--space-2) var(--space-3) var(--space-2) var(--space-5); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--ink-600); font-size: var(--text-xs); line-height: 1.6; }
.experience-detail label { display: flex; flex-direction: column; gap: 4px; color: var(--ink-500); font-size: var(--text-xs); }
.experience-detail input, .experience-detail select, .experience-detail textarea { padding: var(--space-2); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-800); font-size: var(--text-sm); font-family: inherit; }
.experience-meta { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.experience-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
.primary, .ghost { min-height: 38px; padding: 0 var(--space-4); border-radius: var(--radius-md); font-size: var(--text-sm); cursor: pointer; }
.primary { border: 0; background: var(--primary-600); color: var(--surface); }
.ghost { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.primary:disabled, .ghost:disabled { opacity: 0.6; cursor: default; }
@media (max-width: 1280px) {
  .experience-body { grid-template-columns: 1fr; }
}
</style>
