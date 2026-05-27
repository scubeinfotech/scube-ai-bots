# ❓ Unanswered Queries Training Feature

## Overview

The admin dashboard now includes a comprehensive **Query Detail View** that allows you to:
1. ✅ **View full query and response** - Click any query to see complete details
2. 🤖 **Mark for auto-training** - Flag queries to include in LLM fine-tuning
3. 📄 **Upload training documents** - Quick access to document upload for manual training
4. ✅ **Mark as resolved** - Close queries that don't need further action

---

## 🎯 How It Works

### 1. **View Query Details**

**From Admin Dashboard:**
1. Navigate to **❓ Unanswered** tab in the sidebar
2. Click on **any row** in the unanswered queries table
3. A detailed modal opens showing:
   - Full query text
   - Response that was given
   - Confidence score (color-coded: red <0.5, yellow 0.5-0.7, green >0.7)
   - Resolution status
   - Training status

**What You See:**
```
┌─────────────────────────────────────────┐
│ ❓ Query Details & Training Options     │
├─────────────────────────────────────────┤
│ Query: How do I integrate with          │
│        Salesforce?                       │
│                                          │
│ Confidence: 0.3 🔴 | Status: Unresolved │
│                                          │
│ Response: You can integrate with        │
│           Salesforce using our REST...  │
│                                          │
│ 🤖 Mark for Auto-Training               │
│ 📄 Upload Training Document             │
│ ✅ Mark as Resolved                     │
└─────────────────────────────────────────┘
```

---

### 2. **Mark for Auto-Training** 🤖

**Purpose:** Add this question-answer pair to the LLM fine-tuning dataset for automatic improvement.

**How to Use:**
1. Click **"Mark for Training"** button in the query detail modal
2. System flags the query in database with `is_used_for_training = true`
3. Button changes to "Already Marked" (disabled, gray)
4. Status shows: ✓ Marked for Training

**API Call:**
```bash
POST /api/admin/unanswered-queries/{query_id}/mark-for-training
```

**Use Cases:**
- Low confidence responses that were correct but need reinforcement
- Common questions that should be answered better
- Domain-specific terminology the LLM struggled with
- Queries where the response was accurate but could be more comprehensive

**Example Workflow:**
```
User Query: "What are the annual licensing costs?"
LLM Response: "Annual licensing starts at $5000 per year..."
Confidence: 0.4 (Low)

Action: Mark for Training
Result: Next fine-tuning batch includes this Q&A pair
        Future responses have higher confidence
```

---

### 3. **Upload Training Document** 📄

**Purpose:** Provide reference documentation to improve RAG (Retrieval-Augmented Generation) responses.

**How to Use:**
1. Click **"Go to Documents"** button in the query detail modal
2. Modal closes and navigates to **📚 Documents** tab
3. Upload section is highlighted for 3 seconds
4. Upload FAQ, guides, API docs, or training materials

**Document Types Supported:**
- **FAQ** - Question/answer pairs for common queries
- **Guide** - Step-by-step instructions or how-to documents
- **Documentation** - Technical documentation, API references
- **Policy** - Company policies, terms, compliance docs
- **Knowledge Base** - General knowledge articles

**API Call:**
```bash
POST /api/admin/documents/{tenant_id}/upload
Content-Type: multipart/form-data

{
  "name": "Salesforce Integration Guide",
  "content": "Q: How to integrate? A: Step 1...",
  "document_type": "guide"
}
```

**Use Cases:**
- Query about topic not in current knowledge base
- Need to provide official documentation
- Company-specific information not in LLM training data
- Updates to products, services, or policies

**Example Workflow:**
```
Query: "How do I integrate with Salesforce?"
Confidence: 0.3 (Very Low - LLM doesn't know)

Action: Upload "Salesforce_Integration_Guide.pdf"
Result: Document indexed for RAG retrieval
        Future queries pull information from uploaded doc
        Confidence improves to 0.8+
```

---

### 4. **Mark as Resolved** ✅

**Purpose:** Close the query when no further action is needed.

**How to Use:**
1. Click **"Mark Resolved"** button
2. Optionally add resolution notes in the prompt
3. Query status changes to "Resolved"
4. Query moves out of unresolved list (filtered out by default)

**API Call:**
```bash
PATCH /api/admin/unanswered-queries/{query_id}/resolve
Content-Type: application/json

{
  "resolution_notes": "Added to FAQ document"
}
```

**Use Cases:**
- Query was answered satisfactorily after review
- Issue was user error, not knowledge gap
- Query is out of scope for your service
- Already handled through document upload or training

---

## 🔍 Backend API Endpoints

### Get Unanswered Queries
```http
GET /api/admin/unanswered-queries/{tenant_id}?limit=20&resolved_only=false
```

**Response:**
```json
{
  "tenant_id": "scube-id",
  "total": 10,
  "queries": [
    {
      "id": "query-123",
      "query": "How do I integrate with Salesforce?",
      "response": "You can integrate using our REST API...",
      "confidence_score": 0.3,
      "reason": "low_confidence",
      "is_resolved": false,
      "is_used_for_training": false,
      "created_at": "2026-03-10T10:30:00"
    }
  ]
}
```

### Mark for Training
```http
POST /api/admin/unanswered-queries/{query_id}/mark-for-training
```

**Response:**
```json
{
  "id": "query-123",
  "status": "marked_for_training"
}
```

### Resolve Query
```http
PATCH /api/admin/unanswered-queries/{query_id}/resolve
Content-Type: application/json

{
  "resolution_notes": "Optional notes"
}
```

**Response:**
```json
{
  "id": "query-123",
  "status": "resolved"
}
```

---

## 📊 Database Schema

### UnansweredQuery Model
```python
class UnansweredQuery(Base):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    query: str                      # User's question
    response: str                   # LLM's response
    confidence_score: float         # 0.0 to 1.0
    reason: str                     # Why flagged (e.g., "low_confidence")
    is_resolved: bool              # Has admin reviewed?
    is_used_for_training: bool     # Marked for fine-tuning?
    resolution_notes: str          # Admin notes
    created_at: datetime
```

---

## 🎨 UI Features

### Color-Coded Confidence
- 🔴 **Red (0.0-0.4):** Very low confidence - needs attention
- 🟡 **Yellow (0.5-0.6):** Medium confidence - review recommended
- 🟢 **Green (0.7-1.0):** High confidence - resolved or acceptable

### Interactive Table
- **Hover effect:** Rows highlight in blue on hover
- **Click anywhere:** Click any cell to open detail modal
- **Checkbox:** Mark for training directly from table
- **Action buttons:** Quick view/resolve buttons

### Training Options Modal
- **3 Action Cards:**
  1. 🤖 Blue card - Auto-training option
  2. 📄 Green card - Document upload option
  3. ✅ Yellow card - Mark resolved option

---

## 🧪 Testing the Feature

### 1. **Open Admin Dashboard**
```bash
# Open in browser
open admin-dashboard.html
# or
firefox admin-dashboard.html
```

### 2. **Navigate to Unanswered Queries**
- Click **❓ Unanswered** in sidebar
- See sample queries with different confidence scores

### 3. **Test Query Detail View**
```
✓ Click on "How do I integrate with Salesforce?"
✓ Modal opens with full query and response
✓ See confidence score: 0.3 (red badge)
✓ See status: Unresolved
```

### 4. **Test Mark for Training**
```
✓ Click "Mark for Training" button
✓ Alert: "Query marked for LLM training!"
✓ Button becomes disabled and gray
✓ Status shows: "✓ Marked for Training"
```

### 5. **Test Document Upload Navigation**
```
✓ Click "Go to Documents" button
✓ Modal closes
✓ Documents tab opens
✓ Upload section highlighted with green border
```

### 6. **Test Mark as Resolved**
```
✓ Click "Mark Resolved" button
✓ Prompt for optional notes
✓ Status badge changes to green "Resolved"
✓ Button becomes disabled "Already Resolved"
```

---

## 💡 Best Practices

### When to Mark for Training
- **Do:** Low confidence on correct responses
- **Do:** Common questions asked multiple times
- **Do:** Domain-specific queries
- **Don't:** Queries with incorrect responses (fix first)
- **Don't:** One-off unique questions
- **Don't:** Out-of-scope queries

### When to Upload Documents
- **Do:** New product features not in training data
- **Do:** Company-specific information
- **Do:** Recent policy changes
- **Do:** Technical documentation
- **Don't:** Duplicate existing documents
- **Don't:** Outdated information
- **Don't:** Sensitive/confidential data

### When to Mark Resolved
- **Do:** After uploading relevant document
- **Do:** After marking for training
- **Do:** Query is out of scope
- **Do:** User error, not knowledge gap
- **Don't:** Before taking action (training or upload)
- **Don't:** If similar queries keep appearing

---

## 🚀 Production Integration

### Real API Integration
Replace the demo `fetch()` calls with your backend:

```javascript
// Current (Demo with fallback)
fetch(`http://localhost:8001/api/admin/unanswered-queries/${queryId}/mark-for-training`)

// Production (with auth)
fetch(`${API_BASE_URL}/api/admin/unanswered-queries/${queryId}/mark-for-training`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authToken}`,
    'Content-Type': 'application/json'
  }
})
```

### Load Real Data
```javascript
// Fetch real unanswered queries on page load
async function loadUnansweredQueries(tenantId) {
  const response = await fetch(
    `http://localhost:8001/api/admin/unanswered-queries/${tenantId}?limit=50`
  );
  const data = await response.json();
  
  // Populate table with real data
  populateTable(data.queries);
}
```

---

## 📈 Metrics to Track

### Key Performance Indicators
1. **Unanswered Rate:** % of queries with confidence <0.5
   - **Scube:** Currently 10.3%
   - **Target:** <5%

2. **Training Queue:** Number of queries marked for training
   - Track monthly batches
   - Monitor improvement after fine-tuning

3. **Document Coverage:** % of queries with relevant docs
   - Track document upload effectiveness
   - Measure confidence improvement post-upload

4. **Resolution Time:** Average time from flagged → resolved
   - Target: <24 hours for critical queries
   - Track admin engagement

---

## 🔗 Related Features

- **Conversation Viewer:** See full chat context for each query
- **Document Manager:** Upload and process training documents
- **Analytics Dashboard:** View portfolio-wide unanswered rates
- **Tenant Management:** Configure per-tenant training settings

---

**Last Updated:** March 10, 2026  
**Feature Status:** ✅ Ready for Testing  
**API Version:** 1.0.0
