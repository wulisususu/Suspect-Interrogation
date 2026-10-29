<script setup lang="ts">
/**
 * 知识库管理 · 真实功能页（替代 P24 占位）
 *
 * 三个页签：条目（可编辑、带溯源与状态）、热词（同音纠正）、导入记录。
 * 条目来源分 manual / vault；vault 来源的条目说明「改动请回 Obsidian」。
 */
import { computed, onMounted, ref, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import {
  createKnowledgeEntry,
  deleteKnowledgeEntry,
  fetchKnowledgeCategories,
  fetchKnowledgeEntries,
  fetchKnowledgeLinks,
  fetchKnowledgeVersions,
  fetchTermCorrections,
  runKnowledgeImport,
  saveTermCorrection,
  setTermCorrectionActive,
  updateKnowledgeEntry,
  type ImportReport,
  type KnowledgeCategory,
  type KnowledgeEntry,
  type KnowledgeKind,
  type KnowledgeLinks,
  type KnowledgeStatus,
  type KnowledgeVersion,
  type TermCorrection,
} from '../api/knowledge'

type Tab = 'entries' | 'terms' | 'imports'

const tab = ref<Tab>('entries')
const categories = ref<KnowledgeCategory[]>([])
const entries = ref<KnowledgeEntry[]>([])
const corrections = ref<TermCorrection[]>([])
const reports = ref<ImportReport[]>([])
const activeCategory = ref<string>('')
const keyword = ref('')
const statusFilter = ref<'' | KnowledgeStatus>('')
const loading = ref(false)
const error = ref('')
const feedback = ref('')

const selected = ref<KnowledgeEntry | null>(null)
const versions = ref<KnowledgeVersion[]>([])
const links = ref<KnowledgeLinks>({ outgoing: [], incoming: [] })
const editing = ref(false)
const form = ref({ title: '', categoryId: '', content: '', keywords: '', kind: 'faq' as KnowledgeKind, status: 'pending' as KnowledgeStatus, sourceRef: '' })
const saving = ref(false)

const importOpen = ref(false)
const importBusy = ref(false)
const importReport = ref<ImportReport | null>(null)
const termForm = ref({ wrong: '', right: '' })

let searchTimer: ReturnType<typeof setTimeout> | undefined

const counts = computed(() => {
  const verified = entries.value.filter((item) => item.status === 'verified').length
  const vault = entries.value.filter((item) => item.origin === 'vault').length
  return { total: entries.value.length, verified, vault }
})

async function loadCategories() {
  categories.value = await fetchKnowledgeCategories()
  if (!form.value.categoryId && categories.value.length) form.value.categoryId = categories.value[0]!.id
}

async function loadEntries() {
  loading.value = true
  error.value = ''
  try {
    entries.value = await fetchKnowledgeEntries({
      ...(activeCategory.value ? { categoryId: activeCategory.value } : {}),
      ...(keyword.value.trim() ? { q: keyword.value.trim() } : {}),
      ...(statusFilter.value ? { status: statusFilter.value } : {}),
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '知识条目读取失败'
  } finally {
    loading.value = false
  }
}

async function loadCorrections() {
  try {
    corrections.value = await fetchTermCorrections()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '热词读取失败'
  }
}

function scheduleLoad() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { void loadEntries() }, 250)
}

watch(keyword, scheduleLoad)
watch([activeCategory, statusFilter], () => { void loadEntries() })

async function openEntry(entry: KnowledgeEntry) {
  selected.value = entry
  editing.value = false
  form.value = {
    title: entry.title,
    categoryId: entry.categoryId,
    content: entry.content,
    keywords: entry.keywords.join('、'),
    kind: entry.kind,
    status: entry.status,
    sourceRef: entry.sourceRef ?? '',
  }
  versions.value = []
  links.value = { outgoing: [], incoming: [] }
  try {
    const [history, related] = await Promise.all([
      fetchKnowledgeVersions(entry.id),
      fetchKnowledgeLinks(entry.id),
    ])
    versions.value = history
    links.value = related
  } catch {
    /* 详情附属信息失败不阻断主流程 */
  }
}

function startCreate() {
  selected.value = null
  editing.value = true
  form.value = {
    title: '', categoryId: categories.value[0]?.id ?? '', content: '', keywords: '',
    kind: 'faq', status: 'pending', sourceRef: '',
  }
}

async function save() {
  if (!form.value.title.trim() || !form.value.content.trim() || !form.value.categoryId) {
    feedback.value = '标题、分类和正文都不能为空'
    return
  }
  saving.value = true
  feedback.value = ''
  const keywords = form.value.keywords.split(/[、,，\s]+/).map((item) => item.trim()).filter(Boolean)
  try {
    if (editing.value && selected.value) {
      const updated = await updateKnowledgeEntry(selected.value.id, {
        title: form.value.title.trim(),
        categoryId: form.value.categoryId,
        content: form.value.content,
        keywords,
        kind: form.value.kind,
        status: form.value.status,
        sourceRef: form.value.sourceRef.trim() || null,
      })
      selected.value = updated
      feedback.value = `已保存为 v${updated.version}`
      await openEntry(updated)
    } else {
      const created = await createKnowledgeEntry({
        title: form.value.title.trim(),
        categoryId: form.value.categoryId,
        content: form.value.content,
        keywords,
        kind: form.value.kind,
        status: form.value.status,
        sourceRef: form.value.sourceRef.trim() || null,
      })
      feedback.value = '条目已创建'
      await openEntry(created)
    }
    editing.value = false
    await loadEntries()
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function toggleActive(entry: KnowledgeEntry) {
  try {
    const updated = await updateKnowledgeEntry(entry.id, { active: !entry.active })
    if (selected.value?.id === entry.id) selected.value = updated
    await loadEntries()
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '状态更新失败'
  }
}

async function removeEntry(entry: KnowledgeEntry) {
  if (!window.confirm(`删除「${entry.title}」？历史版本会保留。`)) return
  try {
    await deleteKnowledgeEntry(entry.id)
    if (selected.value?.id === entry.id) selected.value = null
    await loadEntries()
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '删除失败'
  }
}

async function dryRun() {
  importBusy.value = true
  feedback.value = ''
  try {
    importReport.value = await runKnowledgeImport({ dryRun: true })
    importOpen.value = true
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '导入预演失败'
  } finally {
    importBusy.value = false
  }
}

async function applyImport() {
  importBusy.value = true
  try {
    const report = await runKnowledgeImport({ dryRun: false })
    importReport.value = report
    feedback.value = `导入完成：新增 ${report.added.length}，更新 ${report.updated.length}，停用 ${report.disabled.length}`
    reports.value.unshift(report)
    await Promise.all([loadEntries(), loadCorrections(), loadCategories()])
    importOpen.value = false
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '导入失败'
  } finally {
    importBusy.value = false
  }
}

async function addTerm() {
  if (!termForm.value.wrong.trim() || !termForm.value.right.trim()) return
  try {
    await saveTermCorrection({ wrong: termForm.value.wrong.trim(), right: termForm.value.right.trim() })
    termForm.value = { wrong: '', right: '' }
    await loadCorrections()
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '热词保存失败'
  }
}

async function toggleTerm(item: TermCorrection) {
  try {
    await setTermCorrectionActive(item.id, !item.active)
    await loadCorrections()
  } catch (err) {
    feedback.value = err instanceof Error ? err.message : '热词状态更新失败'
  }
}

function fmt(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  try {
    await loadCategories()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '分类读取失败'
  }
  await Promise.all([loadEntries(), loadCorrections()])
})
</script>

<template>
  <section class="knowledge-admin">
    <header class="knowledge-head">
      <div>
        <h1>知识库管理</h1>
        <p>共 {{ counts.total }} 条 · 已验证 {{ counts.verified }} 条 · 来自 Vault {{ counts.vault }} 条</p>
      </div>
      <div class="knowledge-head-actions">
        <button type="button" class="ghost" :disabled="importBusy" @click="dryRun">从 Vault 导入</button>
        <button type="button" class="primary" @click="startCreate">＋ 新增条目</button>
      </div>
    </header>

    <nav class="knowledge-tabs" aria-label="知识库分区">
      <button type="button" :class="{ active: tab === 'entries' }" @click="tab = 'entries'">知识条目</button>
      <button type="button" :class="{ active: tab === 'terms' }" @click="tab = 'terms'">热词与纠错</button>
      <button type="button" :class="{ active: tab === 'imports' }" @click="tab = 'imports'">导入记录</button>
    </nav>

    <p v-if="feedback" class="knowledge-feedback" role="status">{{ feedback }}</p>
    <p v-if="error" class="knowledge-error" role="alert">{{ error }}</p>

    <template v-if="tab === 'entries'">
      <div class="knowledge-toolbar">
        <label class="search">
          <span class="sr-only">搜索知识条目</span>
          <input v-model="keyword" type="search" placeholder="搜索标题、正文或关键词" />
        </label>
        <select v-model="statusFilter" aria-label="验证状态">
          <option value="">全部状态</option>
          <option value="verified">已验证</option>
          <option value="pending">待确认</option>
        </select>
      </div>

      <div class="knowledge-body">
        <aside class="knowledge-rail" aria-label="知识分类">
          <button type="button" :class="{ active: !activeCategory }" @click="activeCategory = ''">全部条目</button>
          <button
            v-for="category in categories"
            :key="category.id"
            type="button"
            :class="{ active: activeCategory === category.id }"
            @click="activeCategory = category.id"
          >{{ category.name }}</button>
        </aside>

        <div class="knowledge-main">
          <EmptyState v-if="!entries.length && !loading" kind="empty" title="没有匹配的知识条目" description="可以先用「从 Vault 导入」把 Obsidian 里的笔记同步进来。" />
          <table v-else class="knowledge-table">
            <thead>
              <tr>
                <th>条目</th>
                <th>分类</th>
                <th>状态</th>
                <th>来源</th>
                <th>版本</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in entries" :key="entry.id" :class="{ selected: selected?.id === entry.id, muted: !entry.active }" @click="openEntry(entry)">
                <td>
                  <strong>{{ entry.title }}</strong>
                  <small>{{ entry.kind === 'wiki' ? '概念' : '问答' }} · 更新 {{ fmt(entry.updatedAt) }}</small>
                </td>
                <td>{{ entry.categoryName }}</td>
                <td>
                  <span class="badge" :class="entry.status === 'verified' ? 'ok' : 'warn'">
                    {{ entry.status === 'verified' ? '已验证' : '待确认' }}
                  </span>
                </td>
                <td>
                  <span v-if="entry.origin === 'vault'" class="badge vault" :title="entry.sourcePath || ''">Vault</span>
                  <span v-else class="badge">手工</span>
                </td>
                <td>v{{ entry.version }}</td>
                <td class="row-actions">
                  <button type="button" @click.stop="toggleActive(entry)">{{ entry.active ? '停用' : '启用' }}</button>
                  <button type="button" class="danger" @click.stop="removeEntry(entry)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <aside v-if="selected || editing" class="knowledge-detail" aria-label="条目详情">
          <template v-if="editing">
            <h2>{{ selected ? '编辑条目' : '新增条目' }}</h2>
            <label>标题<input v-model="form.title" maxlength="256" /></label>
            <div class="two-col">
              <label>分类
                <select v-model="form.categoryId">
                  <option v-for="category in categories" :key="category.id" :value="category.id">{{ category.name }}</option>
                </select>
              </label>
              <label>类型
                <select v-model="form.kind">
                  <option value="faq">问答</option>
                  <option value="wiki">概念</option>
                </select>
              </label>
            </div>
            <div class="two-col">
              <label>状态
                <select v-model="form.status">
                  <option value="pending">待确认</option>
                  <option value="verified">已验证</option>
                </select>
              </label>
              <label>溯源<input v-model="form.sourceRef" placeholder="raw/xxx.md" maxlength="512" /></label>
            </div>
            <label>关键词<input v-model="form.keywords" placeholder="用顿号或逗号分隔" /></label>
            <label>正文<textarea v-model="form.content" rows="12" /></label>
            <div class="detail-actions">
              <button type="button" class="ghost" @click="editing = false">取消</button>
              <button type="button" class="primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
            </div>
          </template>

          <template v-else-if="selected">
            <h2>{{ selected.title }}</h2>
            <p class="detail-meta">
              {{ selected.categoryName }} · v{{ selected.version }} ·
              {{ selected.status === 'verified' ? '已验证' : '待确认' }} ·
              {{ selected.origin === 'vault' ? '来自 Vault' : '手工维护' }}
            </p>
            <p v-if="selected.sourceRef" class="detail-source">溯源：{{ selected.sourceRef }}</p>
            <p v-if="selected.origin === 'vault'" class="detail-hint">该条目由 Vault 导入。修改请回 Obsidian，否则下次导入会被覆盖或记为冲突。</p>
            <pre class="detail-content">{{ selected.content }}</pre>
            <div v-if="selected.keywords.length" class="chips">
              <span v-for="word in selected.keywords" :key="word">{{ word }}</span>
            </div>
            <div v-if="links.outgoing.length" class="detail-block">
              <h3>关联（双链）</h3>
              <ul>
                <li v-for="link in links.outgoing" :key="link.targetTitle">
                  {{ link.targetTitle }}<em v-if="!link.resolved">（尚未导入）</em>
                </li>
              </ul>
            </div>
            <div v-if="versions.length" class="detail-block">
              <h3>版本</h3>
              <ul class="version-list">
                <li v-for="item in versions.slice(0, 6)" :key="item.id">v{{ item.version }} · {{ item.action }} · {{ fmt(item.createdAt) }}</li>
              </ul>
            </div>
            <div class="detail-actions">
              <button type="button" class="ghost" @click="editing = true">编辑</button>
              <button type="button" class="ghost" @click="selected = null">关闭</button>
            </div>
          </template>
        </aside>
      </div>
    </template>

    <template v-else-if="tab === 'terms'">
      <div class="knowledge-toolbar">
        <div class="term-form">
          <input v-model="termForm.wrong" placeholder="识别出的错写，如 死老虎派出所" maxlength="128" />
          <span>→</span>
          <input v-model="termForm.right" placeholder="规范写法，如 紫琅湖派出所" maxlength="128" />
          <button type="button" class="primary" @click="addTerm">添加</button>
        </div>
      </div>
      <p class="knowledge-note">热词用于 ASR 输出的确定性短语替换，不修改已定稿笔录。导出后写入 asr-stack 的 corrections.json 需人工确认并重启语音服务。</p>
      <EmptyState v-if="!corrections.length" kind="empty" title="还没有热词" description="在 Obsidian 条目的 frontmatter 里写 corrections，或在上方直接添加。" />
      <table v-else class="knowledge-table">
        <thead><tr><th>误写</th><th>更正</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in corrections" :key="item.id">
            <td><strong>{{ item.wrong }}</strong></td>
            <td>{{ item.right }}</td>
            <td>{{ item.entryId ? '知识条目' : '手工' }}</td>
            <td><span class="badge" :class="item.active ? 'ok' : 'warn'">{{ item.active ? '生效' : '停用' }}</span></td>
            <td class="row-actions"><button type="button" @click="toggleTerm(item)">{{ item.active ? '停用' : '启用' }}</button></td>
          </tr>
        </tbody>
      </table>
    </template>

    <template v-else>
      <EmptyState v-if="!reports.length" kind="empty" title="还没有导入记录" description="每次导入（含预演）都会留下记录，含新增/更新/停用/冲突数量。" />
      <div v-for="report in reports" :key="report.runId || report.root" class="import-card">
        <header>
          <strong>{{ report.dryRun ? '预演' : '导入' }}</strong>
          <span>{{ report.root }}</span>
        </header>
        <p>扫描 {{ report.scanned }} · 新增 {{ report.added.length }} · 更新 {{ report.updated.length }} · 停用 {{ report.disabled.length }} · 冲突 {{ report.conflicts.length }} · 拒绝 {{ report.rejected.length }}</p>
      </div>
    </template>

    <div v-if="importOpen && importReport" class="import-modal" role="dialog" aria-modal="true" aria-label="导入预演">
      <section>
        <h2>导入预演</h2>
        <p class="import-summary">
          扫描 {{ importReport.scanned }} 个文件 · 新增 {{ importReport.added.length }} · 更新 {{ importReport.updated.length }} ·
          停用 {{ importReport.disabled.length }} · 冲突 {{ importReport.conflicts.length }} · 拒绝 {{ importReport.rejected.length }}
        </p>
        <p v-if="importReport.correctionsAdded.length" class="import-line">新增热词 {{ importReport.correctionsAdded.length }} 条</p>
        <ul v-if="importReport.conflicts.length" class="import-list">
          <li v-for="item in importReport.conflicts" :key="item.path">{{ item.path }}：{{ item.reason }}</li>
        </ul>
        <ul v-if="importReport.rejected.length" class="import-list">
          <li v-for="item in importReport.rejected" :key="item.path">{{ item.path }}：{{ item.reason }}</li>
        </ul>
        <p v-if="!importReport.added.length && !importReport.updated.length && !importReport.disabled.length" class="import-line">没有需要变更的条目。</p>
        <footer>
          <button type="button" class="ghost" @click="importOpen = false">取消</button>
          <button type="button" class="primary" :disabled="importBusy" @click="applyImport">
            {{ importBusy ? '导入中…' : '确认导入' }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.knowledge-admin { display: flex; flex-direction: column; gap: var(--space-4); width: 100%; }
.knowledge-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.knowledge-head h1 { margin: 0; color: var(--ink-900); font-size: var(--text-lg); }
.knowledge-head p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.knowledge-head-actions { display: flex; gap: var(--space-2); }
.knowledge-tabs { display: flex; gap: var(--space-2); border-bottom: 1px solid var(--line-300); }
.knowledge-tabs button { padding: var(--space-2) var(--space-3); border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--ink-500); font-size: var(--text-sm); cursor: pointer; }
.knowledge-tabs button.active { border-bottom-color: var(--primary-600); color: var(--primary-700); font-weight: 600; }
.knowledge-toolbar { display: flex; gap: var(--space-3); align-items: center; }
.knowledge-toolbar .search { flex: 1; }
.knowledge-toolbar input, .knowledge-toolbar select { width: 100%; min-height: 40px; padding: 0 var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-800); font-size: var(--text-sm); }
.knowledge-toolbar select { width: 160px; }
.knowledge-body { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.knowledge-body:has(.knowledge-detail) { grid-template-columns: 200px minmax(0, 1fr) minmax(320px, 420px); }
.knowledge-rail { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-2); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); }
.knowledge-rail button { padding: var(--space-2) var(--space-3); border: 0; border-radius: var(--radius-md); background: transparent; color: var(--ink-600); font-size: var(--text-sm); text-align: left; cursor: pointer; }
.knowledge-rail button.active { background: var(--primary-50); color: var(--primary-700); font-weight: 600; }
.knowledge-main { min-width: 0; }
.knowledge-table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--line-300); border-radius: var(--radius-lg); overflow: hidden; }
.knowledge-table th { padding: var(--space-2) var(--space-3); background: var(--surface-sunken); color: var(--ink-500); font-size: var(--text-xs); font-weight: 600; text-align: left; }
.knowledge-table td { padding: var(--space-2) var(--space-3); border-top: 1px solid var(--line-200); color: var(--ink-700); font-size: var(--text-sm); vertical-align: top; }
.knowledge-table tr { cursor: pointer; }
.knowledge-table tr.selected { background: var(--primary-50); }
.knowledge-table tr.muted { opacity: 0.55; }
.knowledge-table td small { display: block; margin-top: 2px; color: var(--ink-400); font-size: var(--text-xs); }
.row-actions { display: flex; gap: var(--space-2); }
.row-actions button { border: 0; background: transparent; color: var(--primary-700); font-size: var(--text-xs); cursor: pointer; }
.row-actions button.danger { color: var(--danger-700); }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; background: var(--surface-sunken); color: var(--ink-600); font-size: var(--text-xs); }
.badge.ok { background: var(--success-50); color: var(--success-700); }
.badge.warn { background: var(--warning-50); color: var(--warning-700); }
.badge.vault { background: var(--primary-50); color: var(--primary-700); }
.knowledge-detail { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-4); border: 1px solid var(--line-300); border-radius: var(--radius-lg); background: var(--surface); max-height: 70vh; overflow: auto; }
.knowledge-detail h2 { margin: 0; color: var(--ink-900); font-size: var(--text-base); }
.knowledge-detail h3 { margin: var(--space-2) 0 var(--space-1); color: var(--ink-600); font-size: var(--text-xs); }
.knowledge-detail label { display: flex; flex-direction: column; gap: 4px; color: var(--ink-500); font-size: var(--text-xs); }
.knowledge-detail input, .knowledge-detail select, .knowledge-detail textarea { padding: var(--space-2); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); color: var(--ink-800); font-size: var(--text-sm); font-family: inherit; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.detail-meta, .detail-source, .detail-hint { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.detail-hint { color: var(--warning-700); }
.detail-content { margin: 0; padding: var(--space-3); border-radius: var(--radius-md); background: var(--surface-sunken); color: var(--ink-700); font-size: var(--text-xs); line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips span { padding: 2px 8px; border-radius: 999px; background: var(--surface-sunken); color: var(--ink-600); font-size: var(--text-xs); }
.detail-block ul { margin: 0; padding-left: var(--space-4); color: var(--ink-600); font-size: var(--text-xs); }
.detail-block em { color: var(--ink-400); font-style: normal; }
.detail-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-2); }
.primary, .ghost { min-height: 38px; padding: 0 var(--space-4); border-radius: var(--radius-md); font-size: var(--text-sm); cursor: pointer; }
.primary { border: 0; background: var(--primary-600); color: var(--surface); }
.ghost { border: 1px solid var(--line-300); background: var(--surface); color: var(--ink-700); }
.primary:disabled, .ghost:disabled { opacity: 0.6; cursor: default; }
.term-form { display: flex; align-items: center; gap: var(--space-2); width: 100%; }
.term-form input { flex: 1; }
.knowledge-note { margin: 0; color: var(--ink-500); font-size: var(--text-xs); }
.knowledge-feedback { margin: 0; color: var(--success-700); font-size: var(--text-xs); }
.knowledge-error { margin: 0; color: var(--danger-700); font-size: var(--text-xs); }
.import-card { padding: var(--space-3); border: 1px solid var(--line-300); border-radius: var(--radius-md); background: var(--surface); }
.import-card header { display: flex; justify-content: space-between; color: var(--ink-600); font-size: var(--text-sm); }
.import-card p { margin: var(--space-1) 0 0; color: var(--ink-500); font-size: var(--text-xs); }
.import-modal { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; padding: var(--space-5); background: rgba(22, 38, 63, 0.72); }
.import-modal section { display: flex; flex-direction: column; gap: var(--space-2); width: min(560px, 100%); padding: var(--space-5); border-radius: var(--radius-lg); background: var(--surface); }
.import-modal h2 { margin: 0; font-size: var(--text-lg); }
.import-summary, .import-line { margin: 0; color: var(--ink-600); font-size: var(--text-sm); }
.import-list { margin: 0; padding-left: var(--space-4); color: var(--ink-600); font-size: var(--text-xs); max-height: 160px; overflow: auto; }
.import-modal footer { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-2); }
@media (max-width: 1280px) {
  .knowledge-body, .knowledge-body:has(.knowledge-detail) { grid-template-columns: 1fr; }
}
</style>
