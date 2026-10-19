# Four-screen UI verification — 2026-10-19

Source visual truth: `D:/微信文件/xwechat_files/wxid_ld4jh285it3l22_717d/msg/file/2026-10/suspect-interrogation-ui-20261019/suspect-interrogation-ui/reference-screens/` — 10-filter-expanded.png, 11-search-empty.png, 08-new-inquiry.png, 02-prepare.png.

Implementation: local production build at `http://127.0.0.1:38082/`, with a read-only API preview forwarding GET requests to the RK3588 using verified project CA TLS. Production writes, card reads, session starts and recording were not exercised through this preview. Existing template initialization POST is deliberately blocked by the preview; its transient 405 message is a preview limitation, not a deployment result.

Evidence directory: `C:/Users/Administrator/.codex/visualizations/2026/10/19/01a15338-fa2c-71a3-8588-e017dc273472/`.

## Captures and comparison

- Desktop CSS viewport: 1920 × 1080. Sources: 3840 × 2160, normalized to 1920 × 1080. Implementation PNGs: 1920 × 1080. CDP full-surface capture was necessary because the app panel screenshot cropped the emulated viewport. Browser emulation was cleared after verification.
- Implementation PNGs: 10-filter-implementation.png, 11-empty-implementation.png, 08-modal-implementation.png, 02-prepare-implementation.png.
- Full-view evidence: qa-full-comparison.png combines each reference and implementation in the same image.
- Focused evidence: qa-modal-focus.png compares modal text, fields and controls; qa-checklist-focus.png compares checklist typography, spacing and state colors.
- State differences: reference card read and 42-second enrollment are illustrated fixtures. The implementation accurately shows unread identity and an unregistered real case; simulated success was not substituted. Actual case types, counts, officers and readiness replace reference example data.

## Findings and iteration history

- Initial [P2]: the search-empty card filled the homepage table area and retained statistics/sidebar, changing the source composition. Fixed with a dedicated centered 820px card and hidden homepage statistics/sidebar for empty search/filter results. Recaptured 11-empty-implementation.png and re-compared in qa-full-comparison.png; resolved.
- Initial [P2]: other workspace tabs exposed the earlier start gate. Fixed by sharing preparationStartGuard and one busy-locked handler across all start controls. Rechecked the disabled start button on both preparation and identity tabs; resolved. Independent code review reported no important remaining findings.

## Required fidelity surfaces

- Typography: existing Microsoft YaHei/PingFang/system fallback retained. Body and buttons use the established enlarged dashboard sizes; checklist headings have clear hierarchy. No clipped labels in desktop or short-screen checks.
- Spacing/layout: source two-column filters, centered dialog, centered empty card and checklist/sidebar structure reproduced. Existing root navigation and workspace utility tabs remain reachable. These retained controls and actual data account for deliberate differences from static references.
- Colors/tokens: existing navy/blue controls, light neutral surfaces, green completion, amber enrollment and muted disabled states match the references' roles.
- Assets: standard icons use the installed icon library. No new raster assets are required. Existing application branding was retained.
- Copy/content: no invented total counts, officer identities, identity-verification claims or successful hardware readings. Manual intake remains available without a configured card reader. Search instructions describe the supported full-name/seven-digit-prefix API behavior.

## Interactions and responsive checks

- Multi-select statuses, applied filter results, reset, open/close and invalid date ordering verified in browser.
- Search-empty state, clear-and-reload, and new inquiry from the empty screen verified.
- Card/manual mode switching, disabled unread-card continuation, initial focus, Escape close and retained manual/card provenance verified without production writes.
- Preparation identity-edit and voiceprint-capture navigation verified; no microphone capture started.
- At 1280 × 720, the preparation body scrolls (614px client / 967px content); scrolling brings the start control into view (top 619.6px, bottom 673.6px). No horizontal overflow in preparation content. Evidence: 02-prepare-short-screen.png.
- Final built-asset preview generated no new console errors. An earlier development-server module/cache error belongs to the abandoned 5174 preview, resolved by verifying the production build instead.
- Frontend tests: 43 files, 243 tests pass using `npm test -- --maxWorkers=2 --no-file-parallelism`. Production build passes. No dependencies or backend/speech code changed.

## Remaining limits / P3

- Physical card reading, real voiceprint enrollment and starting a real interrogation require device/user interaction; existing APIs and guards are retained.
- Pixel-perfect matching of static fixture text, source-only navigation and example dates is intentionally secondary to preserving actual application behavior and enlarged text.

## RK3588 deployment verification

- Frontend manually installed into `/opt/suspect-interrogation/current/webapp/dist` on 2026-10-19.
- Prior dist retained at `/opt/suspect-interrogation/releases/20261008T015528Z-manual/webapp/dist.backup-ui-20261019-163652`.
- Only `interrogation-api.service` restarted, at 16:36:59 CST; PID changed from 619 to 17115, active/running after restart.
- Homepage and all 8 frontend files returned HTTP 200 with SHA-256 matching the local final build. HTTPS verification used the project CA.
- `/health/live` = alive and `/health/ready` = ready, both HTTP 200. Speech socket remains present; protected AI/speech service state/PIDs and TCP/8000 are unchanged.
- Machine, backend source, service configuration and speech services were not changed or rebooted.
- Detailed evidence: `C:/Users/Administrator/.codex/visualizations/2026/10/19/01a15338-fa2c-71a3-8588-e017dc273472/deployment-result-01-04.json`.

## Screen 09 — manual identity entry

- Visual target: the same reference directory's `09-manual-entry.png` (3840 × 2160), normalized to a 1920 × 1080 CSS viewport.
- Final screenshots in the evidence directory: `09-manual-desktop.png`, `09-manual-keyboard.png`, `09-manual-short-candidates.png`, and `09-profile-edit.png`.
- Full-view and focused comparison: `09-qa-comparison.png` contains the reference beside both desktop keyboard states and a close view of field labels/controls. The real existing keyboard has four working rows; the reference depicts an illustrative floating row. This is an intentional functional difference, not a replacement keyboard or simulated input.
- Typography: established Microsoft YaHei/PingFang/system stack; 24px title, 14px labels and 15px inputs/buttons. Labels and values remain legible and consistent with the enlarged application UI.
- Layout: 1180px wide dialog, two field groups, amber review reminder, neutral input surfaces, blue primary action. The same fields are used by intake and in-case identity editing. Existing less frequently used address/unit fields remain available in an expandable section.
- Color/assets: existing navy/blue, light neutral fields and amber reminder palette retained; no raster assets required. Standard library icons retained.
- Copy: no fabricated three-read-failure count, peer-review result or interrogation timestamp. The page requests on-site identity checking; the primary button says save and enter preparation. Inquiry time is read-only and derived by the existing session workflow.
- Initial [P2]: the desktop footer was partly clipped at 1080px height. Reduced field/label spacing while preserving 44px input height. Re-captured the final build: button bottom 1030.8px, dialog bottom 1060.8px, scrollTop 0. Resolved.
- Touch QA: at 1280 × 720 with pinyin candidates, reserved keyboard height is 310.8px; the focused final address field ends at 247.2px and the keyboard starts at 409.2px. Input and footer remain reachable. Closing the keyboard restores dialog height. Touch and viewport emulation were cleared afterward.
- Functional QA: card/manual switching preserves focus; Escape cancels; field validation, read-only inquiry time, collapsible supplemental fields and both entry points verified.
- Isolated write test at port 38083 used synthetic data and never forwarded writes to production. Injected contact-save failure followed by retry produced exactly one intake request and 22 fact writes; all entered fact fields survived and no duplicate case was created. Evidence: `09-preview-requests.json`. The isolated browser tab was closed after testing.
- Independent review caught the backend's default snake-case case type overriding camel-case input. Intake now sends canonical `case_type`; a regression test failed before the fix and passes afterward. Editing also updates case summary type alongside its fact. Review found no remaining important issues.
- Profile update omits unsupported provenance/timestamp fields from the strict existing update schema. Backend and speech code are unchanged.
- Final checks: 45 test files / 247 tests pass; production build and whitespace checks pass. No new console errors from the final read-only preview; the expected injected failure belongs only to the isolated test fixture.

Screen 09 design QA: passed. Physical card reading, live interrogation and a new peer-review backend workflow are outside this frontend change.

Screen 09 deployed on 2026-10-19: API restarted at 17:02:38 CST (PID 17115 → 10290), active/running. Homepage, all 8 frontend files and both health endpoints returned HTTP 200 with project-CA TLS verification; deployed file hashes match the final build. Speech socket and protected AI/speech processes/TCP 8000 are unchanged. Previous frontend retained at `/opt/suspect-interrogation/releases/20261008T015528Z-manual/webapp/dist.backup-ui-20261019-170231`. Detailed evidence: `deployment-result-09.json` in the evidence directory.

final result: passed

## Preparation start button adjustment — 2026-10-19

- Removed automatic footer spacing; the start control follows device checks with a 24px gap. At 1920 × 1080, its top moves from 982.4px to 863.4px (119px upward). At 1280 × 720, scrolling brings the button into view at 467.4–521.4px.
- Production build passes. Preparation tests: 1 file / 6 tests pass using one thread after the first test process encountered host memory pressure.
- Frontend deployed; only API restarted at 17:15:28 CST, PID 10290 → 14720. Homepage, 8 files and health checks verified; protected AI/speech services unchanged. Backup: dist.backup-ui-20261019-171520.
- Offline audit: kiosk uses HTTPS loopback, SQLite is local, deployed LLAMAPI_BASE_URL uses 127.0.0.1:9265, local speech socket and installed models are present. Optional developer BOT judge/dynamic questions use DeepSeek and require Internet. No physical network disconnect/full offline recording test performed.

## Screens 07 and 03 — voiceprint library and suspect capture (2026-10-19)

- Targets: reference-screens/07-voiceprint-library.png and 03-voiceprint-capture.png, 3840 × 2160 source pixels normalized to 1920 × 1080 CSS pixels. Final combined evidence: 07-qa-comparison.png and 03-qa-comparison.png in the existing evidence directory. Capture-state comparison uses an isolated rendering of the real component with synthetic 42 / 60 second state; production was not recorded or mutated.
- Typography: existing application font stack retained; 26px page headings, 13–15px supporting/table text, 15px buttons, 22px reading prompt and 52px measured speech figure. No external font/CDN dependency added.
- Layout: 300px right rail, white 13px-radius cards, profile/sample tables, focused registration form, large capture progress, reading guide and return-to-checklist actions. Retained system calibration tab and in-case navigation rather than removing functional existing destinations.
- Colors: existing navy/blue primary, pale blue reading/progress panels, green registered state, amber recording state and red failure notice. No new raster assets needed. No decorative waveform or invented noise reading substituted for missing live measurements.
- Content: names, sample IDs, durations, timestamps, sample status and aggregate versions come from existing APIs. Selected officer detail remains independently inspectable; truncated sample IDs have full values in details. Real retained/disabled samples and the search field cause density differences versus the fixed reference dataset; the top registration action scrolls and focuses the real form when it lies below the fold. Neutral reading text avoids invented identity facts or statements of voluntariness.
- Initial P2: the first capture-page layout clipped action buttons at 1080p. Tightened page/header/reading spacing without reducing large reading text. Final built production preview: idle button top 892.0px, bottom 944.0px; final recording fixture bottom 973.2px with its 64px test toolbar (production toolbar adds approximately 42px). Resolved.
- Initial P2: global body overflow prevented normal settings-page scrolling to enrollment. Root settings container now has viewport height and overflow:auto. Verified 1080px client / 1303px content and scroll/focus to enrollment; 1280 × 720 has no root horizontal overflow and vertical scrolling reaches the form. Resolved.
- Interaction checks: officer search including no matches, profile switching, sample metadata expansion, registration jump and focus, return to preparation, collapsed optional role binding and 720p scrolling. Existing API actions retained; no production sample was added or disabled.
- State checks in isolated fixture: RECORDING shows measured effective speech; PROCESSING disables recording and return; ERROR shows failure; COMPLETE reports quality/actual duration and enables return. No real microphone permission or capture used. Unit tests cover successful settle/transport-error behavior and preserving the prior voiceprint after failed re-enrollment.
- Validation: full suite 45 files / 249 tests passed. Final focused suite 4 files / 24 tests passed; final vue-tsc and Vite production build passed using a constrained Node heap after host memory pressure. Whitespace check passed. Independent code review found the scrolling issue above and no remaining important API/event/state regressions. Final browser page has no new console warnings/errors.
- P3 / intentional differences: existing navigation retained; sample management displays the selected officer and all retained sample history; page returns through an explicit button rather than inventing resumable pause/cancel behavior unsupported by the existing API. Physical recording and actual hardware enrollment remain for device acceptance.

Screens 07/03 design QA final result: passed.

Screens 07/03 deployed at 17:40:38 CST on 2026-10-19: API active/running, PID 23170. Homepage, all 8 frontend files and health endpoints returned HTTP 200 with CA verification and matching SHA-256 hashes. Protected AI/speech processes, speech socket and TCP/8000 preserved. Backup: /opt/suspect-interrogation/releases/20261008T015528Z-manual/webapp/dist.backup-ui-20261019-174031. Evidence: deployment-result-07-03.json.


## Screens 05/06 and officer enrollment modal — 2026-10-19

- Targets: reference-screens/05-review.png and 06-sign.png, normalized from 3840 x 2160 to 1920 x 1080. Final side-by-side comparisons 05-qa-comparison.png and 06-qa-comparison.png were inspected, along with 05-review-final.png and 06-sign-final.png. Existing navigation is retained. Evidence directory is C:/Users/Administrator/.codex/visualizations/2026/10/19/01a15338-fa2c-71a3-8588-e017dc273472.
- Typography/colors/assets: existing Microsoft YaHei/system stack, navy/blue primary, white cards, pale blue answer fields, amber unresolved fragments and green confirmed states. Legible 14–15px controls/body text retained. No external assets or network font dependency added.
- 05 layout: formal editable record at left and real recognition fragments at right; unresolved-first/time sorting, explicit high-confidence selection and confirmation, original evidence/manual text and speaker corrections, existing question/answer association and pending QA handling. Expanded metadata is available without crowding the record. Large answers auto-size. Unsupported playback is not fabricated.
- 06 layout: actual canonical record on an A4 preview surface with zoom, five initially unchecked manual checks, freeze prerequisites, integrity state, existing electronic signatures and explicit printer confirmation status. Continuous preview uses the browser’s real pagination rather than invented page counts. No paper-signature registration or printer completion is fabricated.
- 07 fix: new officer registration now opens a Teleport modal rather than jumping to an inline form. Supplement-sample entry pre-fills the selected officer. Initial focus, focus trap, Escape/close focus restoration and busy-recording close protection verified. 07-enrollment-modal.png and 07-enrollment-modal-short.png capture the final modal with the existing on-screen keyboard.
- Functional checks used isolated synthetic data with no production write forwarding: high-confidence selection/confirmation, individual confirmation, all-checks freeze gating, frozen record and official print invocation, load failure, long answer wrapping and 1280 x 720 scrolling. Both review/sign layouts have no horizontal overflow; sign checklist remains vertically scrollable. Production data was only read; the read-only preview intentionally rejects template-ensure writes, so loaded nonempty records were tested in the isolated fixture.
- Printed the synthetic frozen record to 06-print-verification.pdf. Both A4 pages were rendered to PNG and inspected: full final answer, signature lines and integrity footer retained; navigation, controls and checklist absent. Physical printer and hardware signature input remain device acceptance checks.
- Independent review found a P2: pending header updates could race with freezing. Added save-in-progress counting across request and refresh, plus case generation guards; reviewer verified the fix. Template loading errors, wrong-case workspace and empty question sets also block freezing. No remaining important review issues.
- Final validation: 47 files / 256 tests passed; vue-tsc and Vite production build passed with the constrained Node heap. Existing uncommitted changes retained. Only frontend files changed for this request.

Screens 05/06 and enrollment modal design QA final result: passed.

Screens 05/06 and officer enrollment modal deployed at Mon 2026-10-19 18:16:48 CST; API active/running, PID 14784. Homepage, all 8 frontend files and both health endpoints returned HTTP 200 with project-CA TLS verification and matching local SHA-256 hashes. Protected AI/speech processes, speech socket and TCP/8000 unchanged. Previous frontend retained at /opt/suspect-interrogation/releases/20261008T015528Z-manual/webapp/dist.backup-ui-20261019-181642. Evidence: deployment-result-05-06-modal.json.


## Workspace navigation consistency — 2026-10-19

- Reproduced the reported jump: preparation header 61px versus profile 84px; tabs 46px versus 50px; button minimum width 130px versus 150px and font 14px versus 16px. Cause: five header/tab overrides were conditional on preparation/voiceprint page selection.
- Applied those existing compact styles to the shared workspace header/navigation across all pages and removed the now-unused conditional root class. No business behavior, data or backend changes.
- Browser verification: preparation/profile/voiceprint/record/MOSS and the record/review/sign modes all retain header height 61px, nav top 61px and nav height 46px at 1920 x 1080. All five buttons remain 130px wide with 14px text. At 1280 x 720, preparation/profile rectangles remain equal; navigation and document widths equal viewport width, with the session actions still visible.
- Evidence: nav-before-prepare.png, nav-before-profile.png, nav-after-prepare.png, nav-after-profile.png, nav-consistency-final.png and nav-measurements.json in the existing artifact directory.
- Validation: 2 relevant files / 14 tests passed, vue-tsc and final Vite build passed. Existing uncommitted work preserved.

Navigation consistency final result: passed.

Navigation fix deployed at Mon 2026-10-19 18:33:30 CST, API active/running PID 13206. Homepage and all 8 files verified against build hashes over project-CA HTTPS; both health endpoints returned 200. Protected AI/speech services, speech socket and TCP/8000 unchanged. Backup: /opt/suspect-interrogation/releases/20261008T015528Z-manual/webapp/dist.backup-ui-20261019-183327. Evidence: deployment-result-navigation.json.
