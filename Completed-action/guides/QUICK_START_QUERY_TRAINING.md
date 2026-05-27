# 🎯 Quick Start: Query Detail & Training Feature

## Visual Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    ADMIN DASHBOARD                              │
│  ┌──────────┐                                                   │
│  │❓Unanswered│◄─── 1. Click to view unanswered queries        │
│  └──────────┘                                                   │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│           UNANSWERED QUERIES TABLE                              │
├─────────────────────────────────────────────────────────────────┤
│ Query                             │ Confidence │ Status         │
│───────────────────────────────────┼────────────┼────────────────│
│ How do I integrate Salesforce? ◄──┼── 🔴 0.3 ──┼── Unresolved  │←2. CLICK ROW
│ What are licensing costs?         │   🟡 0.4   │   Unresolved  │
│ Can I export to PDF?               │   🟢 0.7   │   Resolved    │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│          ❓ QUERY DETAILS & TRAINING OPTIONS                    │
├─────────────────────────────────────────────────────────────────┤
│ 📝 QUERY (from Scube Infotech)                                 │
│ "How do I integrate with Salesforce?"                           │
│                                                                  │
│ Confidence: 0.3 🔴  |  Status: Unresolved                       │
├─────────────────────────────────────────────────────────────────┤
│ 💬 RESPONSE GIVEN                                               │
│ "You can integrate with Salesforce using our REST API..."       │
├─────────────────────────────────────────────────────────────────┤
│ 🎯 TRAINING OPTIONS:                                            │
│                                                                  │
│  ┌────────────────────────────────────────────────┐            │
│  │ 🤖 MARK FOR AUTO-TRAINING                      │            │
│  │ Add this Q&A pair to fine-tuning dataset       │            │
│  │              [Mark for Training] ◄─────────────┼───3. CLICK │
│  └────────────────────────────────────────────────┘            │
│                                                                  │
│  ┌────────────────────────────────────────────────┐            │
│  │ 📄 UPLOAD TRAINING DOCUMENT                    │            │
│  │ Upload FAQ or docs to improve responses        │            │
│  │              [Go to Documents] ◄───────────────┼───4. CLICK │
│  └────────────────────────────────────────────────┘            │
│                                                                  │
│  ┌────────────────────────────────────────────────┐            │
│  │ ✅ MARK AS RESOLVED                            │            │
│  │ Close this query (no action needed)            │            │
│  │              [Mark Resolved] ◄─────────────────┼───5. CLICK │
│  └────────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔥 3-Minute Testing Guide

### Step 1: Open Dashboard (30 seconds)
```bash
cd /home/sudhakar/New-Projects/centralized-llm-platform
open http://localhost:8001/admin   # or firefox/chrome
```

### Step 2: Navigate to Unanswered Queries (10 seconds)
- Click **"❓ Unanswered"** in left sidebar
- See 3 sample queries with different confidence scores

### Step 3: View Query Details (20 seconds)
- Click on **"How do I integrate with Salesforce?"** row
- Modal opens showing:
  - Full query text
  - Response given by LLM
  - Confidence: 0.3 (red - very low)
  - Status: Unresolved

### Step 4: Test Training Options (2 minutes)

#### Option A: Mark for Auto-Training (30 sec)
```
1. Click [Mark for Training] button (blue card)
2. See alert: "Query marked for LLM training!"
3. Button becomes gray/disabled
4. Status shows: "✓ Marked for Training"
```

#### Option B: Upload Document (30 sec)
```
1. Click [Go to Documents] button (green card)
2. Modal closes
3. Documents tab opens automatically
4. Upload section highlighted in green
5. Upload your FAQ/training document here
```

#### Option C: Mark Resolved (30 sec)
```
1. Click [Mark Resolved] button (yellow card)
2. Prompt appears for optional notes
3. Status changes to "Resolved" (green)
4. Button becomes disabled
```

---

## 🎯 Real-World Use Cases

### Scenario 1: Low Confidence Response
```
Problem: LLM answered but confidence is 0.3
Query: "What are the annual licensing costs?"
Response: "Annual licensing starts at $5000..."

Action: Mark for Auto-Training ✓
Why: Response is correct but LLM needs reinforcement
Result: Future queries have higher confidence
```

### Scenario 2: Missing Information
```
Problem: LLM doesn't have the information
Query: "How do I integrate with Salesforce?"
Response: Generic API integration answer
Confidence: 0.3

Action: Upload Document ✓
Document: "Salesforce_Integration_Guide.pdf"
Result: RAG retrieval provides accurate answer
New Confidence: 0.8+
```

### Scenario 3: Out of Scope
```
Problem: Query not relevant to your service
Query: "What's the weather today?"
Response: Generic weather response
Confidence: 0.5

Action: Mark Resolved ✓
Notes: "Out of scope - not a product question"
Result: Query closed, no training needed
```

---

## 📊 Expected Outcomes

### After Marking for Training
- Query flagged in database: `is_used_for_training = true`
- Included in next fine-tuning batch
- LLM learns from this Q&A pair
- Similar future queries answered with higher confidence

### After Uploading Document
- Document processed and indexed for RAG
- Vector embeddings created
- Future queries retrieve relevant sections
- Confidence scores improve for related questions

### After Marking Resolved
- Query status: `is_resolved = true`
- Filtered out of unresolved list by default
- Can still be viewed with "Show Resolved" filter
- Resolution notes saved for audit trail

---

## 🔍 API Testing (Optional)

### Test with curl (if API is running)
```bash
# Get unanswered queries
curl http://localhost:8001/api/admin/unanswered-queries/scube-tenant-id

# Mark for training
curl -X POST http://localhost:8001/api/admin/unanswered-queries/query-123/mark-for-training

# Mark resolved
curl -X PATCH http://localhost:8001/api/admin/unanswered-queries/query-123/resolve \
  -H "Content-Type: application/json" \
  -d '{"resolution_notes": "Added to FAQ"}'
```

---

## ✅ Feature Checklist

**UI Features:**
- [x] Clickable table rows for query details
- [x] Modal with full query and response
- [x] Color-coded confidence badges (red/yellow/green)
- [x] Mark for training button
- [x] Upload document navigation
- [x] Mark resolved button
- [x] Status indicators (resolved/training)
- [x] Tenant identification
- [x] Hover effects on rows
- [x] Close modal on background click

**Backend Integration (Ready):**
- [x] GET /api/admin/unanswered-queries/{tenant_id}
- [x] POST /api/admin/unanswered-queries/{query_id}/mark-for-training
- [x] PATCH /api/admin/unanswered-queries/{query_id}/resolve
- [x] Database model with all required fields
- [x] Confidence score tracking
- [x] Training flag management

**User Experience:**
- [x] One-click query viewing
- [x] Clear action buttons with descriptions
- [x] Visual feedback on actions
- [x] Button state management (disable after action)
- [x] Smooth navigation between tabs
- [x] Helpful tooltips and tips

---

## 🎨 Visual Indicators

### Confidence Score Colors
| Score Range | Color | Badge | Meaning |
|------------|-------|-------|---------|
| 0.0 - 0.4  | 🔴 Red | `badge-danger` | Very Low - Needs Attention |
| 0.5 - 0.6  | 🟡 Yellow | `badge-warning` | Medium - Review Recommended |
| 0.7 - 1.0  | 🟢 Green | `badge-success` | High - Acceptable |

### Status Indicators
| Status | Color | Meaning |
|--------|-------|---------|
| Unresolved | 🟡 Yellow | Needs review/action |
| Resolved | 🟢 Green | Closed/completed |
| ✓ Marked for Training | 🟢 Green | Flagged for fine-tuning |

### Action Card Colors
| Action | Card Color | Icon | Purpose |
|--------|-----------|------|---------|
| Auto-Training | 🔵 Blue | 🤖 | LLM fine-tuning |
| Upload Document | 🟢 Green | 📄 | RAG knowledge base |
| Mark Resolved | 🟡 Yellow | ✅ | Close query |

---

## 🚀 Next Steps

1. **Test the Feature**
   - Open admin-dashboard.html
   - Click through all 3 sample queries
   - Try each action button

2. **Connect to Real API**
   - Ensure services are running: `./service-control.sh status`
   - API should be on http://localhost:8001
   - Test with real backend data

3. **Create Test Data**
   - Run POC tests: `./validate-and-test.sh`
   - Generate conversations with low confidence
   - View actual queries in dashboard

4. **Monitor Improvements**
   - Track unanswered rate: Currently 10.3% (Scube)
   - Goal: Reduce to <5% through training
   - Measure confidence score improvements

---

## 📞 Support

**Files:**
- UI: `/admin-dashboard.html`
- Backend: `/backend/app/api/admin.py`
- Models: `/backend/app/models/knowledge.py`
- Documentation: `/UNANSWERED_QUERIES_FEATURE.md`

**Quick Reference:**
- All ports validated: See `/QUICK-REFERENCE.md`
- Service control: `./service-control.sh`
- Full validation: `./validate-and-test.sh`

---

**Feature Status:** ✅ READY TO USE  
**Testing Required:** 3 minutes  
**Expected Benefit:** Reduce unanswered rate from 10.3% → <5%  
**Last Updated:** March 10, 2026
