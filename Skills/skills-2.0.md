# SKILL: Chatbot LLM Fallback + Embeddings Upgrade
# Version: 2.0
# Purpose: Add Gemini as secondary LLM fallback and embeddings to existing Groq-based chatbot

---

## OVERVIEW

- PRIMARY LLM   : Groq (keep as-is, do not modify)
- FALLBACK LLM  : Gemini Flash (activate only when Groq fails)
- EMBEDDINGS    : Audit existing → replace with Gemini only if insufficient
- API KEYS      : Loaded from .env only, never hardcoded

---

## PART 1 — .ENV CHANGES

Add the following to your `.env` file:

```env
# ─── SECONDARY LLM FALLBACK + EMBEDDINGS (Gemini) ────────
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_FALLBACK_MODEL=gemini-2.0-flash
GEMINI_EMBEDDING_MODEL=models/text-embedding-004

# ─── EXISTING — DO NOT CHANGE ─────────────────────────────
GROQ_API_KEY=your_existing_groq_key
```

Get your Gemini API key:
→ https://aistudio.google.com → Sign in → "Get API Key" → Create → Copy

---

## PART 2 — INSTALL SDK

Run once in your project:

```bash
# Python
pip install google-generativeai
# then add to requirements.txt:
echo "google-generativeai" >> requirements.txt

# Node / TypeScript
npm install @google/generative-ai
```

---

## PART 3 — FALLBACK LLM IMPLEMENTATION

DO NOT touch or refactor any existing Groq code.
Only wrap Groq calls in try/except (Python) or try/catch (JS).

### Python

```python
import os
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel(os.getenv("GEMINI_FALLBACK_MODEL"))

def llm_chat(messages):
    try:
        return groq_chat(messages)  # existing function — do not change
    except Exception as e:
        logger.warning(f"Groq failed: {e} — switching to Gemini fallback")
        prompt = "\n".join([m["content"] for m in messages])
        response = gemini_model.generate_content(prompt)
        return response.text if response.text else ""
```

### JavaScript / TypeScript

```js
import { GoogleGenerativeAI } from "@google/generative-ai";

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const geminiModel = genAI.getGenerativeModel({
  model: process.env.GEMINI_FALLBACK_MODEL
});

async function llmChat(messages) {
  try {
    return await groqChat(messages);  // existing function — do not change
  } catch (e) {
    console.warn("Groq failed, switching to Gemini fallback:", e.message);
    const prompt = messages.map(m => m.content).join("\n");
    const result = await geminiModel.generateContent(prompt);
    return result?.response?.text() ?? "";
  }
}
```

### Rules
- Log which provider responded: "LLM: groq" or "LLM: gemini-fallback"
- Keep the same response format regardless of which provider responds
- Add null/empty checks on Gemini responses before returning

---

## PART 4 — EMBEDDINGS AUDIT + CONDITIONAL REPLACE

### STEP 1: DISCOVER EXISTING EMBEDDINGS (Read-Only)

Search the entire codebase for current embedding implementation.

Look for:
- Functions named  : embed, get_embedding, create_embedding, vectorize
- Imports of       : openai, sentence_transformers, cohere, tiktoken,
                     huggingface_hub, fastembed, chromadb, pinecone, weaviate
- .env keys with   : EMBED, VECTOR, OPENAI (used for embeddings)
- Model strings    : text-embedding-*, all-MiniLM*, ada-002, bge-*

Report findings as:
```
EMBEDDING_PROVIDER = <name or "none found">
EMBEDDING_MODEL    = <model string or "none">
EMBEDDING_LOCATION = <file:line or "none">
EMBEDDING_STATUS   = <"working" | "broken" | "missing" | "paid">
```

---

### STEP 2: EVALUATE — REPLACE OR KEEP?

Apply this decision logic:

```
IF EMBEDDING_STATUS == "working" AND provider is free:
    → KEEP. Print "✅ Embeddings OK — no change needed." and STOP.

IF EMBEDDING_STATUS == "broken" OR "missing":
    → REPLACE with Gemini. Continue to Step 3.

IF provider is paid (OpenAI ada-002, Cohere, etc.):
    → REPLACE with Gemini. Continue to Step 3.

IF provider is slow/low quality (HuggingFace free inference API):
    → REPLACE with Gemini. Continue to Step 3.

IF unsure:
    → Print findings and ASK user before changing anything.
```

---

### STEP 3: REPLACE WITH GEMINI EMBEDDINGS

Only execute this step if Step 2 decision is REPLACE.

Replace the old embedding function IN-PLACE.
Use the SAME function name and return type (flat float array).
Do NOT rename the function — callers must not break.

#### Python

```python
import os
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def get_embedding(text: str) -> list[float]:
    result = genai.embed_content(
        model=os.getenv("GEMINI_EMBEDDING_MODEL"),
        content=text
    )
    return result["embedding"]
```

#### JavaScript / TypeScript

```js
import { GoogleGenerativeAI } from "@google/generative-ai";

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

async function getEmbedding(text) {
  const model = genAI.getGenerativeModel({
    model: process.env.GEMINI_EMBEDDING_MODEL
  });
  const result = await model.embedContent(text);
  return result.embedding.values;  // flat float array
}
```

- Update requirements.txt or package.json with the new SDK
- Remove old unused embedding imports/packages if safe to do so

---

### STEP 4: VECTOR STORE WARNING

IF a vector store exists (Pinecone, Chroma, Qdrant, FAISS, Supabase pgvector):

```
⚠️  WARNING: Embedding model has changed.
    All previously stored vectors are now incompatible.
    You MUST re-index your entire vector database.
    Run your ingestion/indexing pipeline again from scratch
    before using similarity search or RAG features.
```

---

### STEP 5: REPORT BACK

Always finish with a summary:

```
BEFORE:
  Provider : <old provider>
  Model    : <old model>
  Status   : <old status>

AFTER:
  Provider : <gemini | unchanged>
  Model    : <model string | unchanged>
  Action   : <"replaced" | "kept" | "needs review">
  Files changed: <list of files modified>
```

---

## PART 5 — GLOBAL RULES (Apply to All Steps)

- NEVER modify existing Groq code — only wrap it
- NEVER change existing response formats or data structures
- NEVER hardcode API keys — always use os.getenv() or process.env
- NEVER replace a working free embedding without a clear reason
- ALWAYS keep the same function signatures so callers don't break
- ALWAYS add null/empty checks on all Gemini responses
- ALWAYS install SDK and update dependencies file (requirements.txt / package.json)
- IF unsure about any decision → stop and ask the user before proceeding

---

## PART 6 — FINAL VERIFICATION CHECKLIST

After all changes, confirm:

- [ ] Groq still works as primary LLM (no regression)
- [ ] Groq failure silently switches to Gemini fallback
- [ ] get_embedding() / getEmbedding() returns a flat float array
- [ ] No hardcoded API keys anywhere in codebase
- [ ] GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_EMBEDDING_MODEL in .env
- [ ] google-generativeai added to requirements.txt or package.json
- [ ] Vector store re-indexing flagged if embedding model was changed
- [ ] Both Python and JS paths tested (or whichever applies to this project)

---

## PART 7 — FALLBACK TEST (Simulate Groq Outage)

Run this AFTER setup is complete to verify Gemini fallback works correctly
and to compare response quality between Groq and Gemini.

### STEP 1: Add a Test Mode Flag to .env

```env
# Temporary test flag — set to "true" to force Gemini fallback
# REMOVE or set to "false" after testing is done
LLM_FORCE_FALLBACK=false
```

### STEP 2: Update llm_chat to Respect the Flag

Modify the fallback wrapper ONLY — do not touch Groq internals.

#### Python

```python
import os

FORCE_FALLBACK = os.getenv("LLM_FORCE_FALLBACK", "false").lower() == "true"

def llm_chat(messages):
    if FORCE_FALLBACK:
        logger.info("⚠️  TEST MODE: Groq bypassed — using Gemini fallback")
        return _gemini_chat(messages)
    try:
        result = groq_chat(messages)
        logger.info("✅ LLM provider: groq")
        return result
    except Exception as e:
        logger.warning(f"Groq failed: {e} — switching to Gemini fallback")
        return _gemini_chat(messages)

def _gemini_chat(messages):
    prompt = "\n".join([m["content"] for m in messages])
    response = gemini_model.generate_content(prompt)
    logger.info("✅ LLM provider: gemini-fallback")
    return response.text if response.text else ""
```

#### JavaScript / TypeScript

```js
const FORCE_FALLBACK = process.env.LLM_FORCE_FALLBACK === "true";

async function llmChat(messages) {
  if (FORCE_FALLBACK) {
    console.warn("⚠️  TEST MODE: Groq bypassed — using Gemini fallback");
    return await geminiChat(messages);
  }
  try {
    const result = await groqChat(messages);
    console.info("✅ LLM provider: groq");
    return result;
  } catch (e) {
    console.warn("Groq failed, switching to Gemini fallback:", e.message);
    return await geminiChat(messages);
  }
}

async function geminiChat(messages) {
  const prompt = messages.map(m => m.content).join("\n");
  const result = await geminiModel.generateContent(prompt);
  console.info("✅ LLM provider: gemini-fallback");
  return result?.response?.text() ?? "";
}
```

---

### STEP 3: Run Quality Comparison Test

Create a file called `test_llm_compare.py` (or `test_llm_compare.js`) and run it.
This sends the SAME 5 test prompts to BOTH Groq and Gemini and scores them.

#### Python

```python
import os, time
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel(os.getenv("GEMINI_FALLBACK_MODEL"))

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
    elapsed = round((time.time() - start) * 1000)
    return response, elapsed

def test_gemini(prompt):
    start = time.time()
    response = gemini_model.generate_content(prompt)
    elapsed = round((time.time() - start) * 1000)
    return response.text, elapsed

print("\n" + "="*60)
print("LLM QUALITY & SPEED COMPARISON: Groq vs Gemini Flash")
print("="*60)

for i, prompt in enumerate(TEST_PROMPTS, 1):
    print(f"\n📌 TEST {i}: {prompt}")
    print("-"*60)

    groq_resp, groq_ms   = test_groq(prompt)
    gemini_resp, gem_ms  = test_gemini(prompt)

    print(f"⚡ GROQ   ({groq_ms}ms):\n{groq_resp}\n")
    print(f"🔵 GEMINI ({gem_ms}ms):\n{gemini_resp}\n")
    print(f"Speed winner : {'Groq' if groq_ms < gem_ms else 'Gemini'}")
    print("-"*60)

print("\n✅ Test complete. Review responses above.")
print("Set LLM_FORCE_FALLBACK=false in .env when done.\n")
```

#### JavaScript / TypeScript

```js
import { GoogleGenerativeAI } from "@google/generative-ai";
import * as dotenv from "dotenv";
dotenv.config();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const geminiModel = genAI.getGenerativeModel({ model: process.env.GEMINI_FALLBACK_MODEL });

const TEST_PROMPTS = [
  "What is the capital of France?",
  "Explain quantum computing in simple terms.",
  "Write a short professional email declining a meeting.",
  "What are 3 tips for better sleep?",
  "Summarize what a REST API is in 2 sentences."
];

async function testGroq(prompt) {
  const start = Date.now();
  const response = await groqChat([{ role: "user", content: prompt }]);
  return { text: response, ms: Date.now() - start };
}

async function testGemini(prompt) {
  const start = Date.now();
  const result = await geminiModel.generateContent(prompt);
  return { text: result.response.text(), ms: Date.now() - start };
}

(async () => {
  console.log("\n" + "=".repeat(60));
  console.log("LLM QUALITY & SPEED COMPARISON: Groq vs Gemini Flash");
  console.log("=".repeat(60));

  for (let i = 0; i < TEST_PROMPTS.length; i++) {
    const prompt = TEST_PROMPTS[i];
    console.log(`\n📌 TEST ${i+1}: ${prompt}`);
    console.log("-".repeat(60));

    const groq   = await testGroq(prompt);
    const gemini = await testGemini(prompt);

    console.log(`⚡ GROQ   (${groq.ms}ms):\n${groq.text}\n`);
    console.log(`🔵 GEMINI (${gemini.ms}ms):\n${gemini.text}\n`);
    console.log(`Speed winner: ${groq.ms < gemini.ms ? "Groq" : "Gemini"}`);
    console.log("-".repeat(60));
  }

  console.log("\n✅ Test complete. Review responses above.");
  console.log("Set LLM_FORCE_FALLBACK=false in .env when done.\n");
})();
```

---

### STEP 4: What to Look For in Results

After running the comparison, evaluate:

```
SPEED
  ✅ Groq is almost always faster (it uses custom inference chips)
  ✅ Gemini Flash is reasonably fast — acceptable as fallback

QUALITY SIGNALS — Check Gemini responses for:
  ✅ Factually correct answers
  ✅ Appropriate response length (not too short or bloated)
  ✅ Matches tone of your chatbot (professional / casual / technical)
  ✅ No hallucinations on simple factual questions
  ⚠️  If Gemini fails 2+ of 5 prompts → consider a different fallback model

VERDICT GUIDE:
  Groq faster + both quality OK  → Keep setup as-is ✅
  Gemini quality poor            → Switch fallback to gemini-1.5-pro instead
  Both quality good              → You are fully protected ✅
```

---

### STEP 5: After Testing — Clean Up

```env
# In .env — set back to false
LLM_FORCE_FALLBACK=false
```

- Delete test file `test_llm_compare.py` or `test_llm_compare.js` if not needed
- Confirm logs show "LLM provider: groq" on normal requests

---

## PART 8 — EXPECTED FINAL BEHAVIOUR SUMMARY

```
Normal operation:
  User message → Groq (fast) → Response
  Log: "✅ LLM provider: groq"

Groq down / rate limited:
  User message → Groq ❌ → Gemini Flash → Response
  Log: "✅ LLM provider: gemini-fallback"
  User sees NO error — seamless experience

Embeddings:
  Any text → get_embedding() → Gemini text-embedding-004 → float[]
  Used for: RAG, vector search, semantic similarity

Quality expectation:
  Groq  : Faster, slightly more concise
  Gemini: Slightly slower, equally accurate, great fallback
```
