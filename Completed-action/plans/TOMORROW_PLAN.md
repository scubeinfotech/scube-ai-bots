# Tomorrow's Plan — Crawling, Memory, Answer Quality

**Drafted:** end of 2026-04-28 evening session
**Owner:** Sudhakar + Cascade
**Goal:** Improve the data layer (crawling + storage), conversational memory across turns, and overall answer quality.

---

## 2026-04-29 morning — discoveries during pre-work

### Regression bug fixed (out of plan, separate finding)

**`_crawl_site` BFS loop was missing.** During an earlier Playwright refactor the `while queue and len(pages) < max_pages:` loop was deleted, so every crawl returned exactly one page (the start URL) regardless of `MAX_PAGES`. Verified on `jamiyah.org.sg`: pre-fix 1 active page, post-fix 6 active pages.

- File: `backend/app/services/website_crawler.py` (loop restored, JS-render fallback now per-page)
- This was *not* part of any Theme 1 item — Theme 1 items assume a working crawler. Plan items are still all relevant.

### Confirmed during the same crawl

`[RAG] Using hashed fallback embeddings (less accurate)` printed 19× while indexing 6 pages. Confirms Theme 1.3 is the highest-priority remaining crawl item — broken BFS was masking just how poor the embeddings are.

---

## Theme 1 — Crawling, processing, and data store

The current `WebsiteCrawlerService` produces uneven results: some tenants have ~5 chunks of generic homepage HTML, others over-index on header/footer boilerplate, and many have stale data that never refreshes after onboarding. We will revisit the full pipeline.

### 1.1 Crawl strategy
- [ ] Honor `robots.txt` and `<meta name="robots">` per page.
- [ ] Same-origin only (no leaking into third-party CDNs / blogs).
- [ ] Respect `sitemap.xml` when present — prefer it over BFS link-following.
- [ ] Cap pages per crawl (config: `CRAWL_MAX_PAGES`, default 50) and total bytes.
- [ ] Per-tenant concurrency limit (avoid one tenant starving the worker pool).
- [ ] Politeness delay between requests to the same host (configurable).

### 1.2 Content extraction
- [ ] Use a real readability extractor (e.g., `trafilatura` or `readability-lxml`) instead of raw HTML-to-text — strips nav/footer/script/style cleanly.
- [ ] Per-page metadata: title, h1, canonical URL, last-modified, language (langdetect), word count.
- [ ] Drop pages below a min-word threshold (default 50 words) — login pages, redirects, image-only pages.
- [ ] Detect and skip duplicate content via SHA256 over normalized text (catches `?utm_*` permutations of the same URL).

### 1.3 Chunking and embedding
- [ ] Replace fixed-size chunking with **semantic chunking** (split on H1/H2 boundaries; fall back to ~600-token windows with 100-token overlap).
- [ ] Store chunk metadata: `source_url`, `heading_path`, `position`, `language`, `crawl_run_id`.
- [ ] Re-embed only changed chunks on re-crawl (compare hashes). Big cost saver.
- [ ] Move from current hashed-fallback embeddings to a real provider (OpenAI `text-embedding-3-small` is cheap and high-quality, or local `sentence-transformers`). Today's logs showed `Using hashed fallback embeddings (less accurate)` repeatedly — that's the #1 RAG quality bottleneck.

### 1.4 Data store hygiene
- [ ] Add `crawl_runs` table: one row per (tenant_id, started_at, finished_at, pages_processed, errors, status). Surfaces in admin.
- [ ] Soft-delete previous chunks on re-crawl, then activate the new run atomically. Avoids "half-replaced" knowledge during a re-crawl.
- [ ] Per-tenant index in vector store (already there) — add namespace-based `DELETE WHERE crawl_run_id = old`.
- [ ] Admin endpoint to view last crawl error per tenant (today's deferred Phase 3.5 item).

### 1.5 Manual override
- [ ] Admin upload of curated `.txt` / `.md` / `.pdf` files with priority weighting — tenant-authored facts should always beat auto-crawled chunks.
- [ ] Tag-based filtering ("services", "pricing", "policies") so the retriever can prefer the right tag for a given query.

---

## Theme 2 — Memory: remember previous questions and information

Right now the bot has only a sliding window of N recent messages stuffed into the prompt. It forgets:
- What the user said 8 turns ago
- Lead info that was collected mid-conversation (re-asks for it)
- User preferences ("I'm a small business", "based in Singapore")
- The specific product/service path the user is on

### 2.1 Short-term: structured session state
- [ ] Add `chat_sessions.session_facts` JSONB column. Populated by an LLM-or-regex extractor each turn:
  ```json
  { "user_role": "small_business_owner",
    "location": "Singapore",
    "interest": "network_security",
    "budget_range": "$5k-$10k" }
  ```
- [ ] Inject `session_facts` as a `# USER_CONTEXT` section at the top of the system prompt on every turn. Solves the "bot keeps re-asking" problem.

### 2.2 Mid-term: episodic memory across sessions
- [ ] When `lead_phone` or `lead_email` matches an existing record, link new sessions to the same `contact_id`.
- [ ] On session start, fetch last N `session_facts` and last 3 outcomes for the same contact and inject as `# RETURNING_USER_CONTEXT`.
- [ ] Privacy guard: per-tenant flag to disable cross-session memory if the tenant is in a regulated industry.

### 2.3 Conversation summarization
- [ ] When `chat_history_char_budget` overflows (currently truncates from oldest), instead summarize the dropped turns into a one-paragraph `conversation_summary` stored on the session and injected at the top.
- [ ] Cheap to implement: small LLM call (gemini-flash) every N turns.

### 2.4 Lead memory regression
- [ ] Once `session.lead_email` is populated, NEVER re-ask. Today's lead-collection enforcer already respects this — verify and add a unit test.

---

## Theme 3 — Answer quality (continued)

Building on tonight's hallucination guards / RAG threshold / language detection work.

### 3.1 Multi-step / numerical reasoning
- [ ] Detect calculation intents ("how much for 50 users", "what's the total") and route to a structured calculator path, not free-form LLM math.
- [ ] If retrieved context includes a price table, parse it deterministically before generation.

### 3.2 Source citations
- [ ] Append `[1]`, `[2]` markers in the assistant reply that map to retrieved sources, with the actual URLs surfaced in widget UI on hover.
- [ ] Increases trust + lets users verify quickly.

### 3.3 Out-of-scope handling
- [ ] When the user asks something the tenant has zero data for, the bot currently confabulates. Add a confidence threshold based on top RAG score + LLM self-rating; below threshold → respond *"I don't have that information yet — would you like our team to follow up?"* and trigger a lead capture.

### 3.4 Tone and length consistency
- [ ] Today's BEHAVIOR rule "40-100 words max" is often violated. Add a deterministic length cap (truncate at sentence boundary if reply > 600 chars unless user asked for detail).
- [ ] Per-tenant tone config (formal / casual / technical) in `tenant.knowledge_context` — currently it's all "helpful assistant".

### 3.5 Negative-case suite
- [ ] Build a fixture set of 30-50 hard queries we *expect* to fail gracefully (off-topic, prompt-injection attempts, contradictions, made-up product names). Run on every deploy.

### 3.6 Hallucination guard expansion
- [ ] Add `_enforce_no_invented_dates` (years/months) — same approach as pricing.
- [ ] Add `_enforce_no_invented_people_names` — only allow names that appear in `knowledge_context` or retrieved chunks.

---

## Theme 4 — Things carried forward from tonight (deferred)

- [ ] **Phase 3.3** — anonymous welcome rate-limit (needs IP-based limiter; current limiter is per-API-key only)
- [ ] **Phase 3.5** — crawler reliability (now folded into Theme 1)
- [ ] **Phase 4.1** — repo cleanup (`*.backup_*`, `*.py-org`, `chat.py.backup_20260313_150742`, `chat_service.py-org`)
- [ ] **External** — top up OpenRouter credits and/or upgrade Groq tier (today's `ALL PROVIDERS FAILED` events were billing/quota, not code)

---

## Suggested order (rough)

1. **Theme 1.4 + 1.3 (real embeddings + crawl_runs)** — biggest single quality lift; everything downstream improves.
2. **Theme 2.1 (session_facts)** — stops the "re-asks the same question" complaints.
3. **Theme 1.2 (readability extraction)** — pairs well with #1; better input → better embeddings.
4. **Theme 3.3 (out-of-scope handling)** — protects users from confabulation while we improve the data.
5. **Theme 2.3 (summarization)** — once #2 is in, this is small.
6. **Theme 3.1 / 3.2 / 3.5** — incremental polish.

---

## Open questions for Sudhakar before we start

1. Embedding provider preference: OpenAI `text-embedding-3-small` (cheap, ~$0.02 per 1M tokens, best quality) vs local `sentence-transformers/all-MiniLM-L6-v2` (free, decent, needs GPU/CPU)? **My recommendation: OpenAI for prod, local fallback for dev.**
2. Cross-session memory (Theme 2.2): OK for all tenants by default, or opt-in per tenant?
3. Are there 2-3 specific tenants with the worst answer-quality complaints that we should prioritize regression-test fixtures for?
4. Crawl frequency: today scheduled at 03:00 daily — keep, or change to weekly + manual trigger?

---

## Time estimate

| Theme | Hours | Risk |
|---|---|---|
| 1 — Crawling + data store | 4-5 | medium (touches storage layer, needs careful migration) |
| 2 — Memory | 2-3 | low |
| 3 — Answer quality | 2-3 | low |
| Verification + smoke tests | 1 | — |
| **Total** | **~10 hr** (probably 2 sessions) | |

If we're tight: **Theme 1.4 (real embeddings) + Theme 2.1 (session_facts) + Theme 3.3 (out-of-scope)** is the minimum-viable set that will be most user-visible.
