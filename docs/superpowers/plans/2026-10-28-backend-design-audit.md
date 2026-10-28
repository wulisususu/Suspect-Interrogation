# Backend design-audit implementation plan

**Goal:** Implement the backend checklist supplied on 2026-10-28, starting with the three P0 question/recording operations, preserving the frontend at 7cd583b0.

**Spec:** `docs/backend-todo.md` plus the user's detailed checklist in this chat.

**Architecture:** Extend existing SQLAlchemy services and `/api/v1` routes; use separate persistence/services for templates, officers and case administration. Existing case questions, answer rounds and ASR fragments remain the canonical recording and document sources. No parallel rewrite of the application.

**Tech stack:** FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, Alembic, pytest.

## Constraints and decisions

- Responses use `{ok, code, message, data}` and camelCase payloads; preserve existing endpoints and aliases.
- New schema comes with a sequential migration after `0020_drop_moss_transcription` and upgrade/backfill tests.
- Work locally in the existing linked `task17` worktree. Preserve pre-existing untracked user documents. Do not push: pushing this shared branch deploys production.
- Template selection cannot silently discard answered/recorded work, and historical snapshots never change on a catalog update.
- A fact is confirmed while any active linked BODY question has a nonempty canonical answer; drafts do not confirm facts. Fixed sections keep `elementKey=null`.
- Recording target and replacement intent are persisted before collection. Retrying delivery must neither duplicate answers nor erase earlier fragments of the same capture.
- Multi-fragment question creation is transactional, validates same-case ownership and consumed-state compatibility, and must be idempotent.
- Officer authentication is opt-in until an administrator is provisioned; explicitly report configuration state. Never ship default passwords or convert actor IDs supplied by clients into trusted identity.
- Learned-count is maintained explicitly pending a product decision about automatic statistics. Archived-record voiding remains rejected pending the stated policy decision.
- Do not delete historical audit data. Speaker noise can be filtered/categorized; physical voiceprint-table removal is prepared only after runtime/deployment dependencies are removed.
- Frontend visual changes and self-service implementation are out of scope. Add only the API wiring necessary to consume the new backend contracts where required for integration.

## Review focus

1. Cross-case IDs, frozen documents, concurrent retries and partial failures must not mutate unrelated data.
2. Clearing one of multiple answers for an element must not lose the other answer's coverage.
3. Refresh during capture must retain target, source and replace semantics.
4. Template edit/disable must not rewrite existing cases; switching must reject data loss.
5. Authentication, locked/expired sessions, content/media access and audit actor identity must remain consistent.

## Tasks

### 1. P0 questions and capture (root)
- [x] Tests first for element association, aggregate fact states, target capture/recovery and atomic multi-fragment question creation.
- [x] Modify `database/models.py`, `repositories/template_questions.py`, `repositories/asr_fragments.py`, question/capture services, schemas/serializers and routes.
- [x] Migration `0021_question_capture_ownership` after 0020; verify fresh/legacy upgrade.
- [x] Run question, answer, ASR capture/API, freeze-barrier and migration tests.

### 2. Templates and knowledge (template implementer)
- [x] Test catalog, selection/snapshots/blank, new versions/disable, knowledge CRUD/classification/version behavior.
- [x] New `database/catalog_models.py`, `services/template_catalog_service.py`, `api/template_catalog.py`, `api/knowledge.py`, tests, migration `0022_template_knowledge_catalog` after 0021.
- [x] Integrate with existing TemplateWorkspaceService via a dedicated catalog helper; coordinate shared-file changes with root.
- [x] Return schema and integration notes; root registers routes/models and performs combined review.

### 3. Officers, authentication and signatures (identity implementer)
- [x] Tests first for officer CRUD/status, password/session/lock/expiry, officer-role binding, signature validation/version/call audit.
- [x] New `database/officer_models.py`, `services/officer_service.py`, `api/officers.py`, authentication middleware/context and tests.
- [x] Migration `0023_officer_identity` after 0022. Expose safe provisioning with no default secret.
- [x] Coordinate central registration and audit actor propagation with root; do not edit root's shared core files.

### 4. Case lifecycle, audit and validation (workflow implementer)
- [x] Tests first for interruption reason/position, non-archived voiding/reason and frozen mutation rejection, global audit filters/page/result/display.
- [x] New `database/case_management_models.py`, `services/case_management_service.py`, `api/case_management.py`, validation/correction endpoints and tests.
- [x] Migration `0024_case_management` after 0023. Preserve historical logs and categorize speaker events instead of deleting them.
- [x] Expose audit context hooks for authenticated actors; root integrates them.

### 5. Recording/material/device/export integration (root)
- [x] Per-case full-recording option, segmented audio metadata/authorized original access; preserve existing durable archive semantics.
- [x] Existing-case ID read and fingerprint adapter routes with real unsupported-state reporting; do not fabricate hardware evidence.
- [x] Server document generation and export audit/counts with signature/fingerprint snapshots; add required dependencies and tests only as needed.
- [x] Remove residual mandatory voiceprint requirements from runtime/deployment gates without disrupting ASR or TCP/8000; review any physical table removal separately.
- [x] Migrations0025_case_recordings,0026_document_exports,0027_document_fingerprints for the additional recording/export/mark tables.

### 6. Integration and verification (root)
- [x] Register new routes/models without losing existing API contracts; frontend contract/build validation where wiring changes.
- [x] Run scoped tests followed by backend suite and release tests; distinguish reproduced baseline/environment failures by name.
- [x] Review migrations on both fresh and pre-existing database snapshots, downgrade/upgrade where data-preserving.
- [x] Independent review of each subsystem and integrated diff; fix material findings with regressions.
- [x] Update `docs/backend-todo.md` and add endpoint/acceptance documentation reflecting verified, unverified and deferred states.
- [x] Prepare reviewable local commits. Deployment approval is the final external step; no production push or destructive migration without it.

Local implementation and verification are recorded in docs/backend-todo.md. Real fingerprint SDK integration, frontend consumption and production deployment remain external acceptance steps. No push/deploy has been performed.
