# Evening Execution Plan — Production Centralized LLM Platform

**Owner:** Sudhakar + Cascade
**Drafted:** 2026-04-28
**Window:** Late evening (low-traffic)
**Goal:** Stabilize known bugs → improve response quality → tighten tenant isolation → start refactor.

---

## Completed today (afternoon hot-fixes, before the evening window)

- **Nutech Solution widget bug** — tenant reported "Failed to fetch" in the chat widget. Root cause: tenant domain missing from `ALLOWED_ORIGINS` env list, plus malformed `api_keys.allowed_domains` (`"https://www.foo.com/"` instead of bare host).
- **Fixed in `backend/app/api/chat.py:164-218`** — domain-check now normalizes scheme / path / port / `www.` on both sides so stored values like `https://www.foo.com/` still match.
- **Permanent fix for onboarding — dynamic CORS**:
  - New `backend/app/middleware/dynamic_cors.py` — pure ASGI middleware that reads every active tenant's `domain` / `website_url` and every active API key's `allowed_domains` from the DB, merges with a small static base list (dev / admin only), and caches the merged origin set for 60 s.
  - `backend/app/main.py` now uses `DynamicCORSMiddleware` instead of Starlette `CORSMiddleware`.
  - Cache-bust hook `invalidate_cors_cache()` is called from every admin write path that could introduce a new origin: tenant create / update / onboarding-save in `backend/app/api/tenants.py`, admin tenant create / update in `backend/app/api/admin.py`, and widget API-key creation at `backend/app/api/admin.py:2443`. Widget API-key creation also now normalizes `tenant.domain` to a bare host before saving, so new keys never get stored with a scheme/slash.
  - `backend/.env` `ALLOWED_ORIGINS` trimmed to just dev / admin origins, with a comment explaining tenant origins are now dynamic. **No more env edits needed when onboarding a tenant.**
- **Verified**: all 7 active tenants (Nutech, Rapas, Scube, SDS Foodz, Jamiyah, Nivra Studios, Novafarms) — both `www` and bare variants — pass CORS preflight and receive proper `Access-Control-Allow-Origin` on real responses. Attacker origin (`evil.example.com`) is rejected with 400.
- **Backups** kept at `backend/.env.bak.20260428_152800`, `/tmp/apikey_nutech_pre.20260428_152800.csv`.

What this means for the evening plan below:

- **Phase 1 Bug 1.1** (tuple-unpacking 500 at `chat.py:243`) — still pending.
- **Phase 3.4** (domain allowlist hardening) — largely superseded by today's work. Remaining tasks: add `ALLOW_LOCAL_ORIGINS` config flag to gate the private-IP bypass in prod, and decide whether to make `http://` tenant origins opt-in (currently dynamic CORS only emits `https://` variants for tenants, which is already the desired default).
- Everything else in the plan is unchanged.

---

## Pre-flight (do FIRST, before any change)

1. **Snapshot DB**
   ```bash
   cp /home/sudhakar/New-Projects/centralized-llm-platform/backend/llm_platform.db \
      /home/sudhakar/New-Projects/centralized-llm-platform/backend/llm_platform.db.bak.$(date +%Y%m%d_%H%M%S)
   ```
2. **Confirm running service & port**
   ```bash
   ps -ef | grep -E "uvicorn|app.main" | grep -v grep
   curl -s http://localhost:8001/health
   ```
3. **Create a working branch / tag**
   ```bash
   cd /home/sudhakar/New-Projects/centralized-llm-platform
   git status && git stash -u  # if needed
   git checkout -b fix/evening-2026-04-28
   ```
4. **Capture baseline traffic / error sample** (so we can prove improvements)
   - Tail `backend/.runtime/*.log` for last hour, save to `/tmp/baseline.log`.
   - Hit `GET /api/chat/session/<some-existing-id>` with valid `x-api-key` to reproduce the tuple bug → expect `500`.
   - Save 3 sample chat queries per active tenant + their current responses.

---

## PHASE 1 — Known Bugs (target: 30 min)

### 1.1 Fix tuple-unpacking 500 in `get_session_messages`
**File:** `backend/app/api/chat.py:243`
**Bug:** `verify_chat_authorization` returns 3 values; here only 2 are unpacked → `ValueError` → 500.
**Fix:**
```python
# before
authorized, error = verify_chat_authorization(db, session.tenant_id, x_api_key)
# after
authorized, error, _ = verify_chat_authorization(db, session.tenant_id, x_api_key)
```
**Verify:** `curl -H "x-api-key: <widget-key>" http://localhost:8001/api/chat/session/<sid>` → 200/401, never 500.

### 1.2 Per-request LLM provider (don't freeze at module import)
**File:** `backend/app/api/chat.py:92, 209, 248` and `backend/app/api/tenants.py:494`
**Change:** read `os.getenv("LLM_PROVIDER", "mock")` *inside* each handler (or use `settings.llm_provider`). Allows changing provider via env without service restart at the right boundary, and prevents stale config when run via WSGI workers.
**Note:** Do NOT change behavior — just remove the module-level constant.

### 1.3 Remove dead `function_calling` keyword placeholder
**File:** `backend/app/services/chat_service.py:276-302`
**Action:** Delete the keyword-trigger block (it only logs). Replace with a TODO and feature flag check that no-ops cleanly. Real tool execution will land in Phase 2.5.

### 1.4 Increase prompt history window 5 → 10 (configurable)
**File:** `backend/app/services/chat_service.py:370-372`
**Change:** Read `settings.chat_history_turns` (default 10). Add to `app/config.py` (`CHAT_HISTORY_TURNS=10`). Keep token-budget guard — if combined history > ~2000 chars, truncate from the oldest.

### 1.5 Smoke test
- Send a 3-turn conversation per tenant via widget, confirm latencies in logs and no errors.
- Confirm `GET /api/chat/session/{id}` works.
- Confirm Groq (or whichever primary) is still serving.

**Exit criteria:** No 500s in 5-minute log tail; sample conversations identical or better than baseline.

---

## PHASE 2 — Response Quality (target: 60–90 min)

### 2.1 System prompt restructure
**File:** `backend/app/services/chat_service.py::_build_system_prompt` (~L389)
**Action:** Reorganize into 6 explicit sections with section headers the model sees:
```
[IDENTITY]   - tenant.prompt_template + brand
[SCOPE]      - business scope, out_of_scope_mode, CTA goals
[KNOWLEDGE]  - structured tenant knowledge_context
[RETRIEVED]  - RAG vector chunks (only if score above threshold)
[POLICY]     - language policy + behavior rules (deduped, cut from 14+ to ~8)
[STYLE]      - response length, formatting bullets, brand-name preservation
```
Keep existing logic, just rename and consolidate. Don't change defaults.

### 2.2 RAG relevance threshold + dedupe
**File:** `backend/app/services/vector_knowledge.py` and `_build_vector_context`
**Action:**
- Add similarity score threshold (e.g. cosine ≥ 0.55) — drop weak chunks.
- Skip chunks whose text already appears in `knowledge_context` (basic substring/Jaccard check) to stop double injection.
- Cap retrieved tokens (~1500 chars).

### 2.3 Language detection robustness
**File:** `chat_service.py::_infer_response_language` (L503)
**Action:**
- Require a min token count before scoring (if `len(alpha_tokens) < 3`, skip Singlish/Malay scoring → English).
- Lift Tamil-romanized threshold from 2 to 3 to reduce false positives.
- Add unit tests in `tests/test_language_detection.py` with 30 fixtures across 5 languages.

### 2.4 Follow-up enrichment improvements
**File:** `chat_service.py::_enrich_user_message_for_llm` (L734)
**Action:** When previous assistant offered a list (services/products), and current user replies with one item name, inject a hint: *"User selected option X from the previous list; treat as request for details on X."*

### 2.5 Hallucination guards
**File:** new `chat_service.py::_enforce_*` helpers exist; review `_enforce_contact_response` and `_enforce_public_fact_response`.
**Action:**
- Add `_enforce_no_invented_pricing`: if assistant outputs currency + number not present in retrieved/knowledge context → replace with "Please contact us for current pricing".
- Add `_enforce_no_invented_urls`: strip URLs not present in tenant `website_url` or knowledge context.

### 2.6 Regression test set
**File:** new `tests/test_response_quality.py`
**Action:** 5 fixture queries × 5 active tenants (rapas, sdsfoodz, insurance-a, insurance-b, technology). Run in mock mode with stubbed retriever; assert key invariants (no hallucinated phone numbers, brand name preserved, language matches expectation).

**Exit criteria:** Regression suite passes; manual A/B on 3 real queries per tenant shows equal-or-better answers.

---

## PHASE 3 — Multi-tenant Isolation & Onboarding (target: 60 min)

### 3.1 Audit tenant_id filtering
- `grep -rn "ChatMessage.query\|ChatSession.query\|db.query(ChatMessage)\|db.query(ChatSession)" backend/app` — every query must filter by `tenant_id` OR be reached via a session/message already validated.
- `grep -rn "Document.query\|db.query(Document)"` — same.
- Vector store: confirm namespace/collection per tenant in `vector_knowledge.py`.

### 3.2 Widget JWT — actually validate origin
**File:** `backend/app/api/chat.py::verify_widget_token` (L39)
**Action:** Token currently stores `origin` claim but doesn't validate it. Compare against request `Origin` header (with localhost bypass). Reject mismatch.

### 3.3 Anonymous welcome-message path review
**File:** `chat.py:64-74`
**Action:** Currently if `auth_header` is missing, we silently grant access via the first widget API key found for tenant. This is intentional for the welcome message but is a soft attack surface. Add:
- Rate limit by IP for anonymous calls (lower ceiling).
- Restrict anonymous to first message only (block if session already has prior messages from a non-anon source).

### 3.4 Domain allowlist hardening
**File:** `chat.py:174-206`
**Action:** Make private/local IP bypass a config flag (`ALLOW_LOCAL_ORIGINS=false` in production). Log warning when used.

### 3.5 Crawler reliability quick wins
**File:** `backend/app/services/website_crawler.py`
**Action (small):**
- Respect `robots.txt`.
- Skip duplicate-content pages (hash compare).
- Persist last crawl error per tenant for visibility in admin.
- Bigger refactor deferred to Phase 4+.

**Exit criteria:** Cross-tenant query returns no leaked data in audit; widget JWT origin mismatch blocked.

---

## PHASE 4 — Refactor & Cleanup (deferred / later session)

### 4.1 Repo hygiene (do tonight if time permits)
Move (don't delete) to an archive folder for safety:
```bash
mkdir -p _archive/2026-04-28
mv backend/app/api/chat.py.backup_* _archive/2026-04-28/
mv backend/app/services/*.py-org _archive/2026-04-28/
mv backend/app/services/*.py.bak _archive/2026-04-28/
mv backend/static/admin-dashboard.html.bak* _archive/2026-04-28/
mv backend/static/admin-dashboard.html.backup.* _archive/2026-04-28/
```
Keep top-level summary `.md/.txt` for now — will consolidate later.

### 4.2 Split `chat_service.py` (1727 lines) — NEXT SESSION
Plan only, do not start tonight:
- `app/services/chat/prompt_builder.py` — `_build_system_prompt`, `_build_prompt_with_system`, business scope, language policy
- `app/services/chat/language_detector.py` — `_infer_response_language` + hint sets
- `app/services/chat/lead_extractor.py` — `_extract_and_save_lead`
- `app/services/chat/post_processor.py` — `_postprocess_assistant_content`, `_enforce_*`
- `app/services/chat/orchestrator.py` — slim `ChatService.send_message`
- Add `tests/services/chat/` mirroring structure.

---

## Rollback plan

1. **Code:** `git reset --hard <pre-change-commit>` on the branch; restart service.
2. **DB:** `cp llm_platform.db.bak.<ts> llm_platform.db` and restart.
3. **Widget JS:** widget is served from `backend/static/widget.js` and cached `no-store`, so rollback is automatic on file restore.

---

## Verification checklist (run after each phase)

- [ ] `curl http://localhost:8001/health` → 200
- [ ] `pytest tests/ -q` (or targeted subset) → green
- [ ] Manual: send chat per tenant via `/chat/<slug>` widget; assert no 500s.
- [ ] Tail logs 5 min, no new ERROR.
- [ ] Admin dashboard `/admin` loads + analytics responsive.
- [ ] Widget on a tenant's real site (open one) → message round-trip OK.

---

## Open questions for Sudhakar before we start

1. Which tenants are highest priority for response-quality improvements? (rapas / sdsfoodz / insurance-a / insurance-b / technology)
2. Is there a **staging instance** we can hit first, or is this the only deployment?
3. Confirm primary LLM provider in production right now (looks like Groq based on `.env` and code defaults). Any rate-limit concerns we should know about?
4. Any *specific* user-reported quality issues we should prioritize beyond what I've identified? (e.g. "bot hallucinates pricing for tenant X", "wrong language for tenant Y")
5. OK to run the cleanup `mv` step in Phase 4.1 tonight?

---

## Time estimate

| Phase | Minutes | Risk |
|---|---|---|
| Pre-flight | 10 | none |
| Phase 1 — bugs | 30 | low |
| Phase 2 — quality | 90 | medium |
| Phase 3 — isolation | 60 | medium |
| Phase 4.1 — cleanup | 10 | low |
| Buffer / verification | 30 | — |
| **Total** | **~3.5 hr** | |

If we're tight on time: do **Phase 1 + 3.2 (JWT origin) + 2.5 (hallucination guards)** as the minimum-viable set. Defer 2.1 / 2.2 to next session.
