# 前端界面對齊《審訊台產品圖.pdf》實施計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正智能體上一輪（`5e0cd027`、`d38d83b8`、`db7abffa`）前端改動的規範問題，並把設計稿主線 13 屏、附錄 16 屏中尚未實現或偏離的**界面**補齊對齊。本輪只做界面，不新增後端接口、不改業務流程。

**Architecture:** 沿用現有 Vue 3 `<script setup>` + Pinia + 單一 `App.vue` 根頁切換（無 vue-router）。新頁面按「一頁一個 view、可複用塊抽成 component、純計算抽到 `utils/`」拆分；步驟由 `flow/steps.ts` 統一投影。沒有後端數據支撐的區塊一律顯示真實空狀態「功能待接入」，**不造假數據**。

**Tech Stack:** Vue 3.5、TypeScript 5.9、Pinia 3、@lucide/vue、Vitest 4（SSR `renderToString` 斷言，與 `RecordSigningPage.test.ts` 同一寫法）、設計令牌 `src/styles/tokens.css`。

**Spec:** `審訊台產品圖.pdf`（倉庫根目錄，35 頁；頁碼下文寫作 P04…P34）＋ 本計劃「設計稿對照」一節。

## 待你確認的決策（執行前必須定下來）

| # | 問題 | 我的建議（默認） |
|---|---|---|
| D1 | 設計稿是「被害人報案版」，首頁右側「自助模式」及 P07/P11 自助屏是否要做？ | **不做**。嫌疑人詢問不適合當事人自助；首頁只保留人工模式卡，右側位置改放「未完成辦理 + 設備自檢」。 |
| D2 | 附錄 A 後台頁（知識庫、模板管理/編輯、民警簽名、錄音查看）後端沒有接口，要不要先做界面殼？ | **做殼**：頁面骨架、篩選、表頭按設計做，數據區顯示「功能待接入」空狀態。案件記錄、案件詳情、未完成辦理、操作日誌已有接口，做真實數據。 |
| D3 | 全系統品牌統一成哪個？目前大廳是「公安笔录智能工作台」，台賬是「嫌疑人询问系统 · 江北分局 · 刑侦大队」 | 統一為設計稿的「**公安笔录智能工作台**」；單位、大廳名、卷號字頭抽到 `src/config/branding.ts`，不再寫死。 |
| D4 | 審訊頁的「BOT」測試按鈕（會把對話發到雲端） | 雖屬功能問題，但它是界面上的一個按鈕：**本輪隱藏**（僅 `import.meta.env.DEV` 顯示）。 |
| D5 | 「民警驗證」本輪是否接真實認證？ | **不接**。P18 驗證頁只做界面；「验证并继续 / 民警入口」跳到該頁，頁上明確標示「认证尚未接入」。 |

確認後若有改動，我先改本計劃再執行。

## Global Constraints

- 只改 `webapp/`；不改 `linux/backend`、不新增 HTTP 接口、不改 `api/*.ts` 的請求內容。
- 顏色、字號、間距、圓角只用 `tokens.css` 變量；紙質笔录（`--paper-*`）除外，見 Task A1。
- 字號映射固定：12→`--text-xs`、13→`--text-sm`、14→`--text-base`、15→`--text-md`、16/17→`--text-lg`、18–20→`--text-xl`、22–24→`--text-2xl`、28–32→`--text-3xl`；其他值保留字面量並加註釋說明原因。
- 沒有真實數據的區塊統一用 `EmptyState`（Task A6）顯示「功能待接入」，不得出現示例人名、警號、卷號、計數。
- 文案照抄設計稿（簡體中文）；設計稿裡的示例數據（張偉 038291、案 2026-0428 等）不得寫進代碼。
- 觸屏一體機：點擊區不小於 44×44；正文不低於 14px；1280×720 不出現橫向滾動。
- 每個 Task 結束：`npm run typecheck` 通過、`npx vitest run` 全綠，然後單獨提交。
- 按 AGENTS.md：全部完成後走生產部署鏈並完成 11 項驗證，才算完成。

## Review Focus

1. **案件剛建好、模板/問題為空**：①選模板、③問答錄入、④定稿校驗都應顯示空狀態而不是白屏或 `0/0` 怪數字 → Task B2、B4、B5 各加一條空數據渲染測試。
2. **只有一條案件**：台賬那一行不應被拉高填滿表格 → Task A5 加樣式斷言（`align-content: start`）並在截圖驗證中檢查。
3. **1280×720 小屏 + 屏幕鍵盤彈出**：步驟條、頁頭主按鈕不被擠掉或換行 → 驗收清單第 4 項截圖。
4. **已凍結 / 已歸檔案件再進入**：各頁應只讀，編輯類按鈕禁用 → Task B4、B6 加 `frozen: true` 渲染測試。
5. **打印**：簽署頁打印件必須包含已簽名圖片 → Task B6 加測試，斷言簽名 `<img>` 不在 `record-no-print` 容器內。

---

## 設計稿對照（本計劃的依據）

| 設計稿 | 現狀 | 本計劃處理 |
|---|---|---|
| P04 首頁 | 缺自助卡（D1）；未完成提示直接進案件；無底部合規條 | B1 |
| P05 ①選模板 | 無頁面，點①跳到③ | B2 |
| P06 ②建檔 | 結構不同，缺讀卡區、欄位來源標記、完整度條、頁頭按鈕 | B3 |
| P08–10 ③問答錄入 | 缺每題「点击此处回答/重录这题/插入正本」、要素覆蓋條、頁頭「定稿并校验·缺 N 项」 | B4 |
| P12–13 ④定稿校驗 | 定稿前檢查改成了人工勾選；無長按確認 | B5 |
| P14–15 ⑤簽署 | 民警預錄入、指紋彈窗、撤回/作廢按鈕缺；打印件無簽名 | B6 |
| P16 ⑥歸檔 | 版式不同（應為頂部結果卡＋Word/PDF 雙卡） | B7 |
| P18–29 附錄 A | 幾乎全缺 | C1–C5 |
| P31–34 附錄 B | 篩選下拉已做；空/異常/鎖屏、彈窗、播放器缺 | A6、C5、D1 |

---

## Phase A：修正智能體改動的規範問題

### Task A1：修正設計令牌遷移的錯誤映射

`db7abffa` 用色相/明度機械映射，部分映射錯誤，例如 `#edf2f6` 映射成了 `--primary-100`（`tokens.css` 已有完全相同的 `--canvas`），正文色映射成了 `--navy-900`，`styles.css` 的 `:root` 還保留 `Inter` 字體棧，和 `tokens.css` 的 `body` 字體衝突。

**Files:**
- Modify: `webapp/src/styles.css`、`webapp/src/ai-settings.css`、`webapp/src/workspace-pages.css`、`webapp/src/components/templateInterrogation.css`、`webapp/src/components/mossTranscription.css`、`webapp/src/styles/tokens.css`
- Create: `webapp/scripts/check-design-tokens.mjs`
- Test: `webapp/src/styles/tokens.test.ts`

**Interfaces:**
- Produces: `tokens.css` 新增紙質變量 `--paper-bg: #fff; --paper-ink: #242b35; --paper-rule: #dce2eb; --paper-muted: #8c97a6`；`npm run lint:tokens` 命令。

- [ ] **Step 1：寫失敗測試** `tokens.test.ts`：先執行一次 `git show db7abffa -- webapp/src`，把所有「原色值 → 新變量」對提取成固定數據 `src/styles/tokenMigration.fixture.ts`（`Array<{ file: string; from: string; to: string }>`），測試不依賴 git 歷史。對每一對，斷言 `to` 在 `tokens.css` 中的值與 `from` 的 ΔE（CIE76）≤ 3，或列在白名單 `ALLOWED_DRIFT` 中（白名單逐條寫原因）。另斷言 `styles.css` 不再定義 `font-family`。
- [ ] **Step 2：運行** `npx vitest run src/styles/tokens.test.ts`，預期 FAIL，列出 `#edf2f6 → --primary-100` 等漂移項。
- [ ] **Step 3：修正映射**：逐條把漂移項改到最近的已有 token（如 `--canvas`、`--ink-900`）；刪除 `styles.css` 的 `:root` `font-family`；紙質三個組件的字面色改用 `--paper-*`。
- [ ] **Step 4：新增** `scripts/check-design-tokens.mjs`：掃描 `src/**/*.{vue,css}`（排除 `tokens.css`），發現 `#hex` 或 `rgb(` 字面量即以非零退出；`package.json` 增加 `"lint:tokens": "node scripts/check-design-tokens.mjs"`。`RecorderWaveformCanvas.vue` 的 canvas 繪圖色通過 `getComputedStyle` 讀 token。
- [ ] **Step 5：運行** `npx vitest run src/styles/tokens.test.ts && npm run lint:tokens`，預期 PASS、0 處字面色。
- [ ] **Step 6：提交** `style(web): correct token mapping drift and enforce token-only colors`

### Task A2：字號遷移到令牌

全倉 404 處 `font-size: Npx` 字面量，只有 87 處用了 `--text-*`，令牌只落實了顏色。

**Files:**
- Modify: Global Constraints 列出的 CSS 文件，以及 `views/*.vue`、`components/*.vue` 中的 `<style>` 區塊
- Modify: `webapp/scripts/check-design-tokens.mjs`

- [ ] **Step 1：擴展檢查腳本**：`font-size: <數字>px` 也視為違規；允許同一行帶 `/* token-exempt: 原因 */` 的豁免。運行 `npm run lint:tokens`，預期 FAIL，約 404 處。
- [ ] **Step 2：按 Global Constraints 的映射表批量替換**；映射表外的值保留字面量並加豁免註釋。
- [ ] **Step 3：運行** `npm run lint:tokens && npx vitest run`，預期 PASS。
- [ ] **Step 4：截圖回歸**：用驗收清單的截圖腳本，對比首頁、台賬、建檔、問答錄入、定稿校驗前後截圖，肉眼確認無版式錯亂。
- [ ] **Step 5：提交** `style(web): move font sizes onto the type scale tokens`

### Task A3：刪除死組件、修正過期註釋

`CaseListView`、`TranscriptPanel`、`DeviceStatusBar`、`FactMatrix`、`RevisionDrawer` 沒有任何引用，但 `db7abffa` 仍對其中三個做了令牌遷移。`flow/steps.ts` 的註釋仍寫「①–⑤」「五步」，`dictationDone` 裡冗餘判斷了一次 `frozen`。

**Files:**
- Delete: `views/CaseListView.vue`、`views/CaseListView.test.ts`、`components/TranscriptPanel.vue`、`components/DeviceStatusBar.vue`、`components/FactMatrix.vue`、`components/RevisionDrawer.vue`
- Modify: `flow/steps.ts:18-20`、`flow/steps.ts:84-86`
- Create: `flow/steps.test.ts`

**Interfaces:**
- Produces: `resolveFlowProgress(snapshot: FlowSnapshot): FlowProgress`，簽名不變；`dictationDone = intakeDone && hasQuestions`。

- [ ] **Step 1：寫測試** `flow/steps.test.ts`，覆蓋 5 個快照：
  - 全空 → `suggested === 'template'`，`reachable` 等於 `['template','intake']`
  - 有模板、有身份、有聲紋、有問題 → `completed` 含 `intake`，`reachable` 含 `dictation`、`review`
  - `frozen` → `reachable` 含 `signing`
  - `signed` → `reachable` 含 `archive`
  - `archived` → `suggested === 'archive'`
- [ ] **Step 2：運行** `npx vitest run src/flow/steps.test.ts`，預期 PASS（先釘住現有行為）。
- [ ] **Step 3：修正**：刪除死組件；改正註釋為「①–⑥ 六步」；去掉 `dictationDone` 中多餘的 `&& frozen`。若改動導致 `completed` 變化，把該斷言改為新的期望值，並在提交信息中說明。
- [ ] **Step 4：運行** `npm run typecheck && npx vitest run`，預期 PASS。
- [ ] **Step 5：提交** `refactor(web): drop unused screens and pin flow-step projection with tests`

### Task A4：抽出笔录紙面組件，去掉簽署頁/歸檔頁的重複代碼

`RecordSigningPage.vue` 和 `RecordArchivePage.vue` 各自重複實現了 `fact()`、`time()`、卷號拼接、字數統計和整張紙面模板。

**Files:**
- Create: `webapp/src/utils/recordPaper.ts`、`webapp/src/utils/recordPaper.test.ts`、`webapp/src/components/RecordPaper.vue`、`webapp/src/config/branding.ts`
- Modify: `components/RecordSigningPage.vue`、`components/RecordArchivePage.vue`

**Interfaces:**
- Produces:
  - `factValue(facts: FactItem[], key: string, fallback?: string): string`：`'未录入'` 和空串都回退到 `fallback`，默認 `'未填写'`
  - `formatRecordTime(ms?: number | null): string`：空值返回 `'未记录'`
  - `recordWordCount(questions: FormalQuestion[]): number`
  - `branding = { productName: '公安笔录智能工作台', unitName: string, venueName: string, volumePrefix: string | null }`：`unitName`、`venueName`、`volumePrefix` 讀 `import.meta.env.VITE_UNIT_NAME`、`VITE_VENUE_NAME`、`VITE_VOLUME_PREFIX`，未配置時為空串或 `null`
  - `<RecordPaper :summary :facts :session :questions :signing-state :show-hotspots @sign>`，插槽 `#hotspots`
- 卷號：`volumePrefix` 為 `null` 時顯示「卷号待分配」，**不再拼接寫死的 `2026-乙-`**。

- [ ] **Step 1：寫測試** `recordPaper.test.ts`：
  - `factValue([{key:'a',value:'未录入'}],'a') === '未填写'`
  - `formatRecordTime(null) === '未记录'`
  - `recordWordCount([{formalAnswerText:' 你好 '}]) === 2`
- [ ] **Step 2：運行**，預期 FAIL（模塊不存在）。
- [ ] **Step 3：實現** `utils/recordPaper.ts`、`config/branding.ts`、`RecordPaper.vue`，兩個頁面改為使用它們。
- [ ] **Step 4：運行** `npx vitest run`，預期 `RecordSigningPage.test.ts` 與新測試全部 PASS。
- [ ] **Step 5：提交** `refactor(web): share the formal record paper between signing and archive`

### Task A5：可見的界面缺陷

**Files:**
- Modify: `components/VoiceprintAudioSourceBanner.vue`（compact 模式）、`views/CaseDashboardView.vue`（表格容器）、`views/InterrogationWorkspace.vue:392`、`components/LiveDialoguePanel.vue:568-573`、`components/FilterSelect.vue`
- Test: `views/RedesignPhaseOne.test.ts`（追加）

- [ ] **Step 1：寫測試**，用 SSR 渲染斷言：
  - `LiveDialoguePanel` 在非 DEV 環境（`vi.stubEnv('DEV', false)`）不含 `bot-toggle`（D4）
  - `FilterSelect` 展開時每個 `<li>` 帶 `role="none"`
  - `CaseDashboardView` 的表格容器 class 含 `case-table-body`
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：修正**：
  - 頂欄聲源標籤在深色背景上改用 `--primary-100` 文字和 `rgba` 白底（對比度 ≥ 4.5:1）
  - 台賬表格行容器設 `align-content: start`，單行不再被拉高
  - `InterrogationWorkspace.vue:392` 那一行 606 字符的屬性改為一行一個屬性
  - BOT 按鈕加 `v-if="isDev"`
  - `FilterSelect` 的 `<li>` 加 `role="none"`
- [ ] **Step 4：運行**測試，預期 PASS；截圖確認頂欄標籤清晰、單行台賬不被拉高。
- [ ] **Step 5：提交** `fix(web): readable audio-source chip, compact single-row table, dev-only bot`

### Task A6：通用空狀態 / 加載失敗組件（P34 的一部分）

**Files:**
- Create: `components/EmptyState.vue`、`components/EmptyState.test.ts`

**Interfaces:**
- Produces: `<EmptyState kind="empty" | "pending" | "error" :title :description @retry>`
  - `kind="pending"` 固定文案「功能待接入」
  - `kind="error"` 時顯示「重试」按鈕並觸發 `retry` 事件

- [ ] **Step 1：寫測試**：三種 `kind` 各渲染一次；`error` 含「重试」，`pending` 含「功能待接入」。
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**，版式照 P34 左、中兩欄。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): shared empty, pending and error states`

---

## Phase B：主線界面對齊

### Task B1：首頁 · 一體機大廳（P04）

**Files:**
- Modify: `views/KioskHomeView.vue`、`App.vue`
- Create: `views/KioskHomeView.test.ts`

**Interfaces:**
- Consumes: `branding`（A4）
- `KioskHomeView` 的 emits 不變（`start`、`resume`、`policeEntry`）；未完成提示改為 emit `policeEntry`，不再直接 `resume`。

倉庫沒有安裝 `@vue/test-utils`，SSR 也不會執行 `onMounted` 裡的加載。所以把可測部分拆成純函數和純展示組件：`utils/kioskLobby.ts` 導出 `unfinishedCases(cases: CaseSummary[]): CaseSummary[]`（大廳和 C4 共用）；`components/KioskPendingBanner.vue` 只收 `count: number`，emit `verify`。

- [ ] **Step 1：寫測試**（`unfinishedCases` 用純數據測試；`KioskPendingBanner` 傳 `count: 3` 做 SSR 渲染；`KioskHomeView` 做 SSR 首屏渲染）：
  - 文案含「有 3 项未完成办理」「仅显示条数，验证后展开详情」「验证并继续」
  - HTML 中**不出現**任何案件嫌疑人姓名
  - 底部條含「合规」「隐私」「设备」三段
  - 按 D1，不含「自助模式」
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：
  - 未完成提示改成 P04 樣式：點擊「验证并继续」emit `policeEntry`
  - 人工模式卡保留，三步流程文案改為「选模板建档 / 问答与定稿 / 签署打印」及設計稿副文案
  - 設備自檢併入底部三段式條（合规：民警在场确认后定稿 · 隐私：全程保密，仅用于本次办理 · 设备：實時自檢結果）
  - 頂欄品牌與單位讀 `branding`
- [ ] **Step 4：運行**，預期 PASS；截圖與 P04 並排比對。
- [ ] **Step 5：提交** `feat(web): align kiosk lobby with design P04`

### Task B2：①選模板頁（P05）

**Files:**
- Create: `components/TemplatePickerPage.vue`、`components/TemplatePickerPage.test.ts`
- Modify: `views/InterrogationWorkspace.vue`（`WorkspacePage` 增加 `'template'`；`goStep('template')` 打開該頁，不再落到 `'interrogation'`）

**Interfaces:**
- Consumes: `templateStore.workspace`（`templateKey`、`questions`）、`store.facts`
- Props：`templateKey: string | null`、`questions: FormalQuestion[]`、`facts: FactItem[]`
- Emits：`confirm`（跳到 `intake`）

- [ ] **Step 1：寫測試**：
  - 有 `templateKey` 時渲染一張模板卡，標記「✓ 已选此模板」
  - 右側「模板预览」列出 `facts` 的 `label` 作為核心要素，列出前 3 題作為預設問法，並顯示「共 N 条」
  - `questions` 為空時顯示 `EmptyState kind="empty"`
  - 「新建模板」「跳过模板 · 空白笔录」渲染為 `disabled`，title 為「功能待接入」
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：版式照 P05（左側卡片網格 + 頂部分類 + 右側 360px 預覽欄）。分類只有當前一個模板類別時仍渲染「全部 (1)」。頁頭主按鈕「确认模板 · 进入建档 →」emit `confirm`。
- [ ] **Step 4：在** `InterrogationWorkspace.test.ts` **加一條**：`goStep('template')` 後 `activePage === 'template'`。運行全部測試，預期 PASS。
- [ ] **Step 5：提交** `feat(web): template selection step page (P05)`

### Task B3：②建檔 · 身份信息頁（P06）

**Files:**
- Modify: `components/CaseProfilePage.vue`（主體重排）、`components/CasePreparationPage.vue`（保留開始前檢查，作為建檔子頁「询问准备」）
- Create: `components/IdentityFieldRow.vue`、`components/CaseProfilePage.test.ts`

**Interfaces:**
- `<IdentityFieldRow label :value :source="'CARD' | 'MANUAL' | 'AUTO'" :required :editable>`，右側標籤分別顯示「身份证读取 / 手工补填 / 自动推算」

- [ ] **Step 1：寫測試**：
  - `summary.identitySource === 'MANUAL'` 時各行標記「手工补填」
  - 頁頭含「暂存草稿」「下一步 · 问答录入 →」
  - 底部「建档核对 · 信息完整度 N%」按必填欄位實際填寫比例計算：給定 8 個必填中填了 6 個 → `75%`
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：
  - 左欄「身份证读取」卡：讀卡能力不可用時顯示「读卡器未配置 · 可手工录入」
  - 右欄「被询问人身份信息」和「询问信息」兩組欄位
  - 底部完整度條
  - 「下一步」調用 `goStep('dictation')`
  - 「暂存草稿」復用現有保存邏輯
- [ ] **Step 4：運行**，預期 PASS；截圖對比 P06。
- [ ] **Step 5：提交** `feat(web): identity intake layout per P06`

### Task B4：③問答錄入（P08–P10）

**Files:**
- Modify: `components/DraftQuestionRail.vue`、`components/TemplateDrivenInterrogationPage.vue`、`views/InterrogationWorkspace.vue`（頁頭主按鈕）
- Create: `components/FactCoverageBar.vue`、`utils/factCoverage.ts`、`utils/factCoverage.test.ts`、`components/DraftQuestionRail.test.ts`

**Interfaces:**
- Produces: `factCoverage(facts: FactItem[]): { total: number; covered: number; missing: FactItem[] }`，`covered` 計 `status === 'confirmed'`
- `DraftQuestionRail` 新增 emits：`recordQuestion: [questionId]`（目前轉調全局 `captureToggle`）、`insertToRecord: [questionId]`（目前轉調已有 `updateAnswer`）

- [ ] **Step 1：寫測試**：
  - `factCoverage` 對 6 條中 4 條 confirmed 返回 `{ total: 6, covered: 4 }`
  - 卡片在無答案時含「点击此处回答」，有答案時含「重录这题」「插入正本 →」
  - `locked: true` 時這三個按鈕都是 `disabled`
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：
  - 卡片底部按鈕組照 P08；錄音中的卡片用 P10 的紅框樣式，並顯示「录音中 mm:ss」
  - 正本上方 `FactCoverageBar`：「依据模板 · N 项要素 · 已覆盖 x/N」，缺項 chips 最多 3 個 +「补齐缺项 →」，點擊跳 `review`
  - 頁頭主按鈕「定稿并校验 · 缺 N 项」，`N = missing.length`
- [ ] **Step 4：運行**，預期 PASS；截圖對比 P08。
- [ ] **Step 5：提交** `feat(web): draft cards, coverage bar and finalize CTA per P08-P10`

### Task B5：④定稿校驗（P12–P13）

**Files:**
- Modify: `components/ReviewChecklistPanel.vue`
- Create: `utils/longPress.ts`、`utils/longPress.test.ts`、`components/LongPressButton.vue`、`components/ReviewChecklistPanel.test.ts`

**Interfaces:**
- `<LongPressButton :duration-ms="800" :disabled @confirm>`：按住滿 800ms 才 emit `confirm`，鬆開提前取消；可見進度條；鍵盤 Enter 長按同樣生效
- `ReviewChecklistPanel` 新增 prop `autoChecks: Array<{ key: string; title: string; state: 'pass' | 'pending' | 'unavailable'; detail: string }>`

- [ ] **Step 1：寫測試**：
  - 測試環境是 node、沒有 DOM，所以把計時邏輯抽成 `utils/longPress.ts`：`createLongPress(durationMs: number, onConfirm: () => void): { start(): void; cancel(): void; progress(): number }`，`LongPressButton` 只負責轉發 pointer 和鍵盤事件。用 `vi.useFakeTimers()` 測：`start()` 後推進 799ms 未觸發；推進到 800ms 觸發；中途 `cancel()` 則不觸發
  - 面板渲染 4 行自動校驗，標題分別為「模板要素」「时间线一致」「同音字纠错」「签署人数与身份」
  - `state: 'unavailable'` 時顯示「待接入」
  - 計數行「N 项检查 · x 项通过 · y 项待确认」
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：
  - 「模板要素」由 `factCoverage` 計算
  - 「签署人数与身份」由聲紋 readiness 中的民警綁定計算
  - 「时间线一致」「同音字纠错」本輪固定 `unavailable`
  - 保留原 5 項人工勾選，放在自動校驗下方，標題「民警确认」
  - 主按鈕換成 `LongPressButton`，文案「确认定稿 · 正本冻结并进入签署（长按 800ms）」，原 `freeze` 事件不變
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): review checklist auto checks and long-press finalize per P12-P13`

### Task B6：⑤簽署歸檔（P14–P15）

**Files:**
- Modify: `components/RecordSigningPage.vue`、`components/TemplateDrivenInterrogationPage.vue`（簽名彈窗）
- Create: `components/SignatureHotspotDialog.vue`

**Interfaces:**
- `<SignatureHotspotDialog role="SUSPECT" | "FINGERPRINT" | "OFFICER" :officers :busy @cancel @confirm-handwritten @confirm-preset>`
  - `SUSPECT`：保留現有手寫畫布
  - `FINGERPRINT`：顯示「0 / 1 枚 · 请按压采集窗」，因為無設備，確認按鈕 `disabled`，提示「未接入采集器」
  - `OFFICER`：列出 `officers`（現有民警聲紋庫名單）作為「预录入调用」選項；本輪沒有預錄簽名數據，每行顯示「未预录入签名」，提供「改为现场手写」入口

- [ ] **Step 1：寫測試**（在 `RecordSigningPage.test.ts` 追加）：
  - 簽名進度顯示「x / 3 处」
  - 側欄含「撤回定稿」「作废笔录」，均 `disabled`，title「功能待接入」
  - 已簽名的 `<img>` 不在任何 `.record-no-print` 祖先內（Review Focus 第 5 條）
  - `frozen` 狀態下紙面不出現可編輯控件
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：
  - 熱區與簽名圖分離：熱區按鈕 `record-no-print`，簽名圖始終渲染在紙面簽名行
  - 三處熱區都打開 `SignatureHotspotDialog`
  - 側欄「笔录状态 / 打印与装卷」字段順序照 P15
  - 打印機、份數、紙張改為只讀展示，卷號讀 `branding.volumePrefix`
- [ ] **Step 4：運行**，預期 PASS；打開打印預覽確認簽名可見。
- [ ] **Step 5：提交** `feat(web): signing hotspot dialogs and printable signatures per P14-P15`

### Task B7：⑥歸檔結果（P16）

**Files:**
- Modify: `components/RecordArchivePage.vue`
- Create: `components/RecordArchivePage.test.ts`

- [ ] **Step 1：寫測試**：
  - 頂部結果卡含「归档成功 · 办结」和 4 個信息塊（卷号、归档人 · 时间、签章、录音 · 文书）
  - 下方兩張導出卡分別為「导出 Word」「导出 PDF」，各帶 3 條說明
  - 無 `volumePrefix` 時卷號塊顯示「卷号待分配」
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：版式照 P16；紙面預覽移到「导出 PDF」打印時使用（復用 `RecordPaper`，屏上不展示整頁紙）。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): archive result layout per P16`

---

## Phase C：附錄 A 後台管理（按 D2）

### Task C1：統一後台外殼與民警驗證頁（P18–P19）

**Files:**
- Create: `components/AdminShell.vue`、`views/AdminPanelView.vue`、`views/AdminPanelView.test.ts`
- Modify: `App.vue`（`RootPage` 增加 `'admin' | 'admin-cases' | 'admin-case' | 'admin-pending' | 'admin-audit' | 'admin-placeholder'`，URL 參數沿用 `view=`，案件詳情帶 `adminCaseId=`）、`views/LoginView.vue`

**Interfaces:**
- `<AdminShell :title @back>`：深色頂欄「公安笔录一体机 · 后台管理」，左上「‹ 返回管理面板」，右上「锁定面板」（emit `lock`，Task D1 使用）
- `LoginView` 的「登录」本輪仍不認證（D5），預覽說明保留；新增「进入管理面板（预览）」按鈕 emit `admin`

- [ ] **Step 1：寫測試**：
  - 管理面板渲染 4 個入口（案件记录、知识库、民警签名、录音查看）
  - 外加「未完成办理」「模板管理」「操作日志」快捷入口
  - 每個入口有標題、說明和圖標
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：`App.vue` 原有的根導航條（「系统设置 · 民警声纹库」「登录页预览」）改由 `AdminShell` 承載；大廳「民警入口」→ `LoginView` → `AdminPanelView`。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): admin shell, panel and verification entry (P18-P19)`

### Task C2：全部案件記錄（P20）

**Files:**
- Modify: `views/CaseDashboardView.vue`（套進 `AdminShell`；篩選改為「关键字 / 状态 / 主审」三項，與 P20 一致；統計卡和右側欄移除）
- Test: `views/RedesignPhaseOne.test.ts`（更新現有斷言）

- [ ] **Step 1：更新測試**：
  - 表頭為「案件编号 / 案由 / 状态 / 主审 / 更新时间 / 操作」
  - 操作列按狀態渲染：已歸檔「导出 Word」「导出 PDF」，已簽署「补签」「导出」，進行中「继续办理」，待定稿「补录」「预览」
  - 本輪無接口的操作 `disabled` 並帶 title「功能待接入」；「继续办理」可用
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**，點擊行打開 `admin-case`（C3）。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): case ledger per P20`

### Task C3：案件詳情（P21–P22）

**Files:**
- Create: `views/AdminCaseDetailView.vue`、`views/AdminCaseDetailView.test.ts`

**Interfaces:**
- Consumes: 現有 `fetchCase`、`fetchFacts`、`fetchDocumentSigningState`、`fetchTemplateWorkspace`
- 已歸檔：全部只讀；未歸檔：顯示「继续办理」（emit `open`，走現有 `openCase`）

- [ ] **Step 1：寫測試**：
  - 要素覆蓋區（`factCoverage`）、簽章區、文書區（`RecordPaper` 只讀）、錄音區（`EmptyState kind="pending"`）都存在
  - `workflowState === 'REPORT_GENERATED'` 時不含「继续办理」
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**，版式照 P21；P22 的「标注缺项原因」本輪只渲染缺項列表，不做提交。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): read-only case detail per P21-P22`

### Task C4：未完成辦理與操作日誌（P23、P29）

**Files:**
- Create: `views/AdminPendingView.vue`、`views/AdminAuditView.vue`、`api/audit.ts`、`views/AdminPendingView.test.ts`

**Interfaces:**
- `fetchCaseAudit(caseId: string): Promise<AuditEntry[]>`：走已存在的 `audit.list` 操作；`AuditEntry` 按後端返回字段定義
- 未完成辦理直接用 B1 的 `unfinishedCases()`；在該函數中統一排除純 `DRAFT`（P23：「仅『草稿』不计入本列表」），大廳計數因此同步變化

- [ ] **Step 1：寫測試**：
  - 給 5 條案件（含 1 條 DRAFT、1 條已歸檔）→ 列表顯示 3 條，標題「未完成办理 · 共 3 项」
  - 操作日誌頁沒有選中案件時顯示 `EmptyState`
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**：操作日誌頁按案件選擇後拉取；頁上註明「只读留置，不可删除」。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): pending cases and audit log views (P23, P29)`

### Task C5：無接口頁面殼（P24–P28、P32）

**Files:**
- Create: `views/AdminPlaceholderView.vue`、`views/AdminPlaceholderView.test.ts`

**Interfaces:**
- `<AdminPlaceholderView kind="knowledge" | "templates" | "template-edit" | "signatures" | "recordings">`：按 kind 渲染對應 P24–P28 的頁頭、篩選條、表頭或分欄骨架，數據區統一 `EmptyState kind="pending"`
- `signatures` 的「新增 / 更换」按鈕打開 P32 簽名預錄入彈窗殼，`recordings` 渲染 P32 播放器殼，確認按鈕都 `disabled`

- [ ] **Step 1：寫測試**：
  - 5 個 kind 各渲染一次，斷言頁標題分別為「知识库管理」「模板管理」「模板编辑」「民警签名管理（预先录入）」「录音查看 · 双通道双文件」
  - 每個都含「功能待接入」
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): admin placeholder screens for knowledge base, templates, signatures, recordings`

---

## Phase D：全局狀態

### Task D1：鎖屏（P34 右欄）

**Files:**
- Create: `components/LockScreen.vue`、`components/LockScreen.test.ts`
- Modify: `App.vue`

**Interfaces:**
- `App.vue` 持有 `locked: Ref<boolean>`，`AdminShell` 的 `lock` 事件設為 `true`
- `LockScreen` 覆蓋全屏，按鈕「民警验证解锁」跳 `LoginView`
- 本輪不做「10 分钟免验」計時（需要認證，D5）

- [ ] **Step 1：寫測試**：`locked` 時渲染「已锁屏」和「民警验证解锁」，業務內容不在 DOM 中。
- [ ] **Step 2：運行**，預期 FAIL。
- [ ] **Step 3：實現**。
- [ ] **Step 4：運行**，預期 PASS。
- [ ] **Step 5：提交** `feat(web): manual lock screen (P34)`

---

## 最終驗收（全部 Task 完成後）

1. `npm run typecheck`、`npm run lint:tokens`、`npx vitest run` 全部通過。
2. 本機隔離環境截圖：臨時 SQLite 後端，`127.0.0.1`，合成數據，不連生產。依次截首頁、①–⑥、管理面板、台賬、詳情、未完成、日誌、5 個殼頁、鎖屏，分辨率 1600×900 和 1280×720。
3. 把每張截圖與 PDF 對應頁並排生成對照圖，逐屏列出剩餘差異（只允許「真實數據替代示例數據」「功能待接入」兩類差異）。
4. 1280×720 + 屏幕鍵盤彈出時，步驟條和頁頭主按鈕可見，無橫向滾動。
5. 按 AGENTS.md 執行 RK3588 生產部署鏈的 11 項驗證；未全部通過時，如實報告「code committed, production deployment incomplete」。
