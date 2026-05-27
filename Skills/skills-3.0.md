# SKILL: Chatbot LLM Fallback + Embeddings Upgrade
# Version: 3.0
# Purpose: Audit existing LLM router, wire Gemini fallback properly,
#          add embeddings, test and compare quality vs Groq.

---

## OVERVIEW

- PRIMARY LLM   : Groq (keep as-is, never modify)
- FALLBACK LLM  : Gemini Flash (wire into existing router)
- TERTIARY LLM  : OpenRouter (already in .env, keep as last resort)
- EMBEDDINGS    : Audit existing → replace with Gemini only if insufficient
- API KEYS      : Loaded from .env only, never hardcoded

---

## KNOWN .ENV (Already Exists — Do Not Overwrite)

```env
GEMINI_API_KEY=<already set>
OPENAI_API_KEY=<already set>
OPENROUTER_API_KEY=<already set>
LLM_PROVIDER=router
LLM_PRIMARY=groq
LLM_SECONDARY=gemini
LLM_TERTIARY=openrouter
LLM_GEMINI_MODEL=gemini-2.0-flash
LLM_PROVIDER_TIMEOUT_MS=30000
LLM_MAX_RETRIES=1
LLM_GROQ_MODEL=gemma-7b-it
```

Only ADD these lines if they are missing:

```env
# Add only if not already present:
GEMINI_EMBEDDING_MODEL=models/text-embedding-004
LLM_FORCE_FALLBACK=false
```

---

## PART 1 — AUDIT FIRST (READ-ONLY, NO CHANGES YET)

This step is mandatory. Do not skip or modify any files here.

### STEP 1A: Find the Router / LLM Dispatcher

Search the codebase for files that read these .env keys:
  LLM_PROVIDER, LLM_PRIMARY, LLM_SECONDARY, LLM_TERTIARY

Look for files named:
  llm.py, router.py, provider.py, chat.py, ai.py
  llm.js, router.js, provider.js, chat.js, ai.js, llm.ts

Report:
```
ROUTER_FILE      = <filename:line or "not found">
ROUTING_LOGIC    = <"exists" | "missing" | "partial">
GROQ_WIRED       = <"yes" | "no">
GEMINI_WIRED     = <"yes" | "no" | "partial">
OPENROUTER_WIRED = <"yes" | "no">
FALLBACK_ORDER   = <"groq→gemini→openrouter" | "other" | "none">
FALLBACK_LOGIC   = <"exists" | "missing">
```

### STEP 1B: Check Gemini Integration Status

Since LLM_SECONDARY=gemini is already in .env, verify if it is actually
implemented in code:

Check for:
  - Is google-generativeai or @google/generative-ai installed?
  - Is GEMINI_API_KEY being read anywhere in code?
  - Is LLM_GEMINI_MODEL being used?
  - Does Gemini actually get called or is it declared but not wired?

Report:
```
GEMINI_SDK_INSTALLED = <"yes" | "no">
GEMINI_KEY_READ      = <"yes" | "no">
GEMINI_MODEL_USED    = <"yes" | "no">
GEMINI_CALL_EXISTS   = <"yes" | "no" | "partial">
GEMINI_GAP           = <describe what is missing or "none">
```

### STEP 1C: Check Embeddings

Search entire codebase for embedding implementation:

Look for:
  - Functions : embed, get_embedding, create_embedding, vectorize
  - Packages  : openai (embeddings), sentence_transformers, fastembed,
                chromadb, pinecone, weaviate, supabase, qdrant, faiss
  - .env keys : EMBED*, VECTOR*, anything used for embeddings

Report:
```
EMBEDDING_PROVIDER = <name or "none">
EMBEDDING_MODEL    = <model string or "none">
EMBEDDING_LOCATION = <file:line or "none">
EMBEDDING_STATUS   = <"working" | "broken" | "missing" | "paid">
VECTOR_STORE       = <"pinecone"|"chroma"|"faiss"|"supabase"|"none">
```

### STEP 1D: Print Full Audit Summary

```
══════════════════════════════════════════════════
AUDIT SUMMARY
══════════════════════════════════════════════════
ROUTER FILE      : <file>
GROQ             : <wired / not wired>
GEMINI           : <wired / partial / not wired>
OPENROUTER       : <wired / not wired>
FALLBACK ORDER   : <groq→gemini→openrouter / other / none>
EMBEDDINGS       : <provider / missing>
VECTOR STORE     : <name / none>

ISSUES FOUND:
  - <list every gap, missing wire, broken logic>

RECOMMENDED ACTIONS:
  - <exact list of what needs to be done>
══════════════════════════════════════════════════
```

STOP HERE. Show the audit summary and wait for user confirmation
before making any code changes.

---

## PART 2 — INSTALL SDK (Only If Missing)

Only run if GEMINI_SDK_INSTALLED = "no" from audit.

```bash
# Python
pip install google-generativeai
echo "google-generativeai" >> requirements.txt

# Node / TypeScript
npm install @google/generative-ai
```

---

## PART 3 — WIRE GEMINI INTO EXISTING ROUTER

Only execute based on audit findings. Do NOT rewrite the router.
Extend it minimally — add only what is missing.

### Decision Logic

```
IF GEMINI_WIRED == "yes" (fully working):
    → SKIP this part. Print "✅ Gemini already wired." and move to Part 4.

IF GEMINI_WIRED == "partial":
    → Fill in only the missing pieces identified in audit.

IF GEMINI_WIRED == "no":
    → Add Gemini as secondary in the existing router pattern.
```

### Python — Extend Existing Router

```python
import os
import google.generativeai as genai

# Initialize Gemini once at startup
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
_gemini_model = genai.GenerativeModel(
    os.getenv("LLM_GEMINI_MODEL", "gemini-2.0-flash")
)

def _call_gemini(messages: list[dict]) -> str:
    """Gemini secondary — called when Groq fails."""
    prompt = "\n".join([m["content"] for m in messages])
    response = _gemini_model.generate_content(prompt)
    return response.text if response and response.text else ""

def llm_chat(messages: list[dict]) -> str:
    """
    Router: Groq (primary) → Gemini (secondary) → OpenRouter (tertiary)
    Reads LLM_PRIMARY, LLM_SECONDARY, LLM_TERTIARY from env.
    """
    FORCE_FALLBACK = os.getenv("LLM_FORCE_FALLBACK", "false").lower() == "true"

    if FORCE_FALLBACK:
        logger.info("⚠️  TEST MODE: Groq bypassed — using Gemini")
        return _call_gemini(messages)

    # Primary: Groq
    try:
        result = groq_chat(messages)   # existing function — do not modify
        logger.info("✅ LLM provider: groq")
        return result
    except Exception as e:
        logger.warning(f"Groq failed: {e}")

    # Secondary: Gemini
    try:
        result = _call_gemini(messages)
        logger.info("✅ LLM provider: gemini")
        return result
    except Exception as e:
        logger.warning(f"Gemini failed: {e}")

    # Tertiary: OpenRouter (existing function — do not modify)
    try:
        result = openrouter_chat(messages)
        logger.info("✅ LLM provider: openrouter")
        return result
    except Exception as e:
        logger.error(f"All LLM providers failed: {e}")
        raise
```

### JavaScript / TypeScript — Extend Existing Router

```ts
import { GoogleGenerativeAI } from "@google/generative-ai";

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY!);
const _geminiModel = genAI.getGenerativeModel({
  model: process.env.LLM_GEMINI_MODEL ?? "gemini-2.0-flash"
});

async function _callGemini(messages: {role: string, content: string}[]): Promise<string> {
  const prompt = messages.map(m => m.content).join("\n");
  const result = await _geminiModel.generateContent(prompt);
  return result?.response?.text() ?? "";
}

export async function llmChat(messages: {role: string, content: string}[]): Promise<string> {
  const FORCE_FALLBACK = process.env.LLM_FORCE_FALLBACK === "true";

  if (FORCE_FALLBACK) {
    console.warn("⚠️  TEST MODE: Groq bypassed — using Gemini");
    return await _callGemini(messages);
  }

  // Primary: Groq
  try {
    const result = await groqChat(messages);  // existing — do not modify
    console.info("✅ LLM provider: groq");
    return result;
  } catch (e: any) {
    console.warn("Groq failed:", e.message);
  }

  // Secondary: Gemini
  try {
    const result = await _callGemini(messages);
    console.info("✅ LLM provider: gemini");
    return result;
  } catch (e: any) {
    console.warn("Gemini failed:", e.message);
  }

  // Tertiary: OpenRouter (existing — do not modify)
  try {
    const result = await openrouterChat(messages);
    console.info("✅ LLM provider: openrouter");
    return result;
  } catch (e: any) {
    console.error("All LLM providers failed:", e.message);
    throw e;
  }
}
```

### Rules
- NEVER rewrite the existing router from scratch — only extend it
- NEVER modify groqChat() or openrouterChat() internals
- ALWAYS log which provider responded on every call
- ALWAYS add null/empty checks on Gemini responses
- ALWAYS keep the same return type as existing llm_chat

---

## PART 4 — EMBEDDINGS AUDIT + CONDITIONAL REPLACE

### STEP 4A: Evaluate from Audit Results

```
IF EMBEDDING_STATUS == "working" AND provider is free:
    → KEEP. Print "✅ Embeddings OK — no change needed." and STOP.

IF EMBEDDING_STATUS == "broken" OR "missing":
    → REPLACE with Gemini. Continue to Step 4B.

IF provider is paid (OpenAI ada-002, Cohere, etc.):
    → REPLACE with Gemini. Continue to Step 4B.

IF provider is slow/low quality (HuggingFace free tier):
    → REPLACE with Gemini. Continue to Step 4B.

IF unsure:
    → Show findings and ASK user before changing anything.
```

### STEP 4B: Replace Embeddings with Gemini

Replace the old function IN-PLACE.
Use the SAME function name and return type (flat float array).
Do NOT rename — callers must not break.

#### Python

```python
import os
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def get_embedding(text: str) -> list[float]:
    """Returns a 768-dim embedding vector using Gemini text-embedding-004."""
    result = genai.embed_content(
        model=os.getenv("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004"),
        content=text
    )
    return result["embedding"]
```

#### JavaScript / TypeScript

```ts
import { GoogleGenerativeAI } from "@google/generative-ai";

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY!);

export async function getEmbedding(text: string): Promise<number[]> {
  const model = genAI.getGenerativeModel({
    model: process.env.GEMINI_EMBEDDING_MODEL ?? "models/text-embedding-004"
  });
  const result = await model.embedContent(text);
  return result.embedding.values;  // flat float array, 768 dims
}
```

### STEP 4C: Vector Store Warning

IF VECTOR_STORE is not "none":

```
⚠️  WARNING: Embedding model has changed.
    All previously stored vectors are now INCOMPATIBLE.
    You MUST re-index your entire vector database.
    Run your ingestion/indexing pipeline again from scratch
    before using similarity search or RAG features.
    Do NOT use the old index with the new embedding model.
```

### STEP 4D: Embeddings Report

```
BEFORE:
  Provider : <old provider>
  Model    : <old model>
  Status   : <old status>

AFTER:
  Provider : <gemini | unchanged>
  Model    : <models/text-embedding-004 | unchanged>
  Action   : <"replaced" | "kept" | "needs review">
  Files changed : <list>
```

---

## PART 5 — TEST & QUALITY COMPARISON

Run AFTER all wiring is complete.

### STEP 5A: Force Gemini to Test It

Set in .env temporarily:
```env
LLM_FORCE_FALLBACK=true
```

Send a few real chat messages through the bot and confirm:
- Gemini responds correctly
- Logs show "LLM provider: gemini"
- Response format matches what Groq normally returns

### STEP 5B: Run Side-by-Side Comparison Script

Create `test_llm_compare.py` or `test_llm_compare.ts` and run once.
DELETE the file after testing is done.

#### Python

```python
import os, time
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel(
    os.getenv("LLM_GEMINI_MODEL", "gemini-2.0-flash")
)

TEST_PROMPTS = [
    "What is the capital of France?",
    "Explain quantum computing in simple terms.",
    "Write a short professional email declining a meeting.",
    "What are 3 tips for better sleep?",
    "Summarize what a REST API is in 2 sentences."
]

def test_groq(prompt):
    start = time.time()
    response = groq_chat([{"role": "user", "content": prompt}])
    return response, round((time.time() - start) * 1000)

def test_gemini(prompt):
    start = time.time()
    response = gemini_model.generate_content(prompt)
    return response.text, round((time.time() - start) * 1000)

print("\n" + "="*60)
print("LLM COMPARISON: Groq vs Gemini Flash")
print("="*60)

for i, prompt in enumerate(TEST_PROMPTS, 1):
    print(f"\n📌 TEST {i}: {prompt}")
    print("-"*60)
    groq_resp, groq_ms  = test_groq(prompt)
    gemini_resp, gem_ms = test_gemini(prompt)
    print(f"⚡ GROQ   ({groq_ms}ms):\n{groq_resp}\n")
    print(f"🔵 GEMINI ({gem_ms}ms):\n{gemini_resp}\n")
    print(f"Speed winner : {'⚡ Groq' if groq_ms < gem_ms else '🔵 Gemini'}")
    print("-"*60)

print("\n✅ Comparison complete.")
print("→ Set LLM_FORCE_FALLBACK=false in .env when done.\n")
```

#### JavaScript / TypeScript

```ts
import { GoogleGenerativeAI } from "@google/generative-ai";
import * as dotenv from "dotenv";
dotenv.config();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY!);
const geminiModel = genAI.getGenerativeModel({
  model: process.env.LLM_GEMINI_MODEL ?? "gemini-2.0-flash"
});

const TEST_PROMPTS = [
  "What is the capital of France?",
  "Explain quantum computing in simple terms.",
  "Write a short professional email declining a meeting.",
  "What are 3 tips for better sleep?",
  "Summarize what a REST API is in 2 sentences."
];

async function testGroq(prompt: string) {
  const start = Date.now();
  const text = await groqChat([{ role: "user", content: prompt }]);
  return { text, ms: Date.now() - start };
}

async function testGemini(prompt: string) {
  const start = Date.now();
  const result = await geminiModel.generateContent(prompt);
  return { text: result.response.text(), ms: Date.now() - start };
}

(async () => {
  console.log("\n" + "=".repeat(60));
  console.log("LLM COMPARISON: Groq vs Gemini Flash");
  console.log("=".repeat(60));

  for (let i = 0; i < TEST_PROMPTS.length; i++) {
    const prompt = TEST_PROMPTS[i];
    console.log(`\n📌 TEST ${i + 1}: ${prompt}`);
    console.log("-".repeat(60));
    const groq   = await testGroq(prompt);
    const gemini = await testGemini(prompt);
    console.log(`⚡ GROQ   (${groq.ms}ms):\n${groq.text}\n`);
    console.log(`🔵 GEMINI (${gemini.ms}ms):\n${gemini.text}\n`);
    console.log(`Speed winner: ${groq.ms < gemini.ms ? "⚡ Groq" : "🔵 Gemini"}`);
    console.log("-".repeat(60));
  }
  console.log("\n✅ Comparison complete.");
  console.log("→ Set LLM_FORCE_FALLBACK=false in .env when done.\n");
})();
```

### STEP 5C: How to Evaluate Results

```
SPEED
  ✅ Groq is almost always faster (custom inference chips)
  ✅ Gemini Flash is acceptable speed for a fallback

QUALITY — Check Gemini responses for:
  ✅ Factually correct answers
  ✅ Appropriate response length
  ✅ Matches your chatbot tone
  ✅ No hallucinations on simple questions
  ⚠️  If Gemini fails 2+ of 5 → change LLM_GEMINI_MODEL=gemini-1.5-pro in .env

VERDICT:
  Both quality OK + Groq faster    → Setup is perfect ✅
  Gemini quality poor              → Change model in .env only, no code change
  Both good, Gemini sometimes faster → Keep as-is, Groq still primary ✅
```

### STEP 5D: Clean Up After Testing

```env
# .env — reset after testing
LLM_FORCE_FALLBACK=false
```

- Delete `test_llm_compare.py` or `test_llm_compare.ts`
- Confirm normal logs show "✅ LLM provider: groq"

---

## PART 6 — GLOBAL RULES (Always Apply)

- NEVER rewrite existing router from scratch — only extend
- NEVER modify groqChat() or openrouterChat() internals
- NEVER hardcode API keys — always use os.getenv() or process.env
- NEVER replace working free embeddings without clear reason
- ALWAYS keep same function names and return types
- ALWAYS add null/empty checks on all Gemini responses
- ALWAYS update requirements.txt or package.json when adding SDK
- ALWAYS log which LLM provider responded on every call
- IF unsure about any decision → STOP and ask user first

---

## PART 7 — FINAL VERIFICATION CHECKLIST

After all changes, confirm every item:

```
LLM ROUTING
  [ ] Groq responds on normal requests (no regression)
  [ ] Groq failure → Gemini responds automatically
  [ ] Gemini failure → OpenRouter responds automatically
  [ ] Logs show correct provider name on every request
  [ ] LLM_FORCE_FALLBACK=false in .env (test flag off)

GEMINI SETUP
  [ ] GEMINI_API_KEY read from .env (never hardcoded)
  [ ] LLM_GEMINI_MODEL used (gemini-2.0-flash)
  [ ] google-generativeai in requirements.txt or package.json

EMBEDDINGS
  [ ] get_embedding() / getEmbedding() returns flat float array
  [ ] GEMINI_EMBEDDING_MODEL=models/text-embedding-004 in .env
  [ ] Vector store re-index flagged if embedding model changed

SECURITY
  [ ] No API keys hardcoded anywhere in codebase
  [ ] .env is in .gitignore
  [ ] Test comparison files deleted after use

QUALITY
  [ ] Groq vs Gemini comparison completed and reviewed
  [ ] Both providers return acceptable quality responses
```

---

## PART 8 — EXPECTED FINAL BEHAVIOUR

```
NORMAL OPERATION (99% of requests):
  User → Groq (fast) → Response
  Log : "✅ LLM provider: groq"

GROQ DOWN / RATE LIMITED:
  User → Groq ❌ → Gemini Flash → Response
  Log : "✅ LLM provider: gemini"
  User sees no error — seamless experience

ALL PRIMARY PROVIDERS DOWN:
  User → Groq ❌ → Gemini ❌ → OpenRouter → Response
  Log : "✅ LLM provider: openrouter"
  Last resort safety net

EMBEDDINGS:
  Text → get_embedding() → Gemini text-embedding-004 → float[768]
  Used for: RAG, vector search, semantic similarity

SPEED EXPECTATION:
  Groq          : Fastest  (~200–400ms)
  Gemini Flash  : Fast enough (~500–900ms)
  OpenRouter    : Slowest, last resort only

QUALITY EXPECTATION:
  Groq   : Fast, concise, reliable
  Gemini : Equally accurate, great fallback
  Users notice no difference in output quality
```
