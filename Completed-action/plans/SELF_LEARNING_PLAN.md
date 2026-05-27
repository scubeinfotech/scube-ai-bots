# Self-Learning Chatbot Plan

## Vision
The chatbot should continuously learn from daily conversations to improve responses over time without manual intervention.

## Current State
- Chatbot uses static knowledge base from crawled documents
- No automatic learning from conversations
- Unanswered queries are tracked but not used for learning

## Proposed Self-Learning System

### Phase 1: Conversation Analysis (Daily)
- Run daily scan of all conversations from past 24 hours
- Identify successful conversations (user satisfied, got answer)
- Identify failed conversations (unanswered, low confidence)

### Phase 2: Knowledge Extraction
From successful conversations:
- Extract Q&A pairs where assistant gave good answers
- Add to knowledge base as new documents
- Tag with conversation metadata

From failed conversations:
- Mark queries for admin review
- Create training data for later

### Phase 3: Auto-Tuning
- Analyze response patterns
- Adjust temperature/tone based on feedback
- Learn preferred response lengths

### Phase 4: Continuous Improvement
- Weekly knowledge base updates
- Monthly model fine-tuning (if needed)
- Quarterly performance reports

## Technical Implementation

### 1. Daily Job - Extract Q&A Pairs
```
Job: scan_conversations_for_learning
Schedule: Daily at 2am
Steps:
1. Get all sessions from past 24 hours
2. For each session:
   - Check if user gave positive feedback
   - Check if query was answered (not flagged as unanswered)
   - Extract: user_query + assistant_response
3. Store as potential training data
4. Flag for admin review (not auto-add)
```

### 2. Auto-Update Knowledge Base
```
New Document Type: "learned"
Fields:
- source_conversation_id
- user_query (anonymized)
- assistant_response
- confidence_score
- created_at
- status: "pending_review" | "approved" | "rejected"
```

### 3. Response Quality Tracking
- Track thumbs up/down feedback
- Track if user continued conversation (implied satisfaction)
- Track query resolution time

### 4. Admin Panel Updates
- Add "Learning" section in admin dashboard
- Show learned Q&A pairs for review
- Allow approve/reject for knowledge base
- Show learning statistics

## Data Flow

```
Daily Conversations
       ↓
[Analysis Job]
       ↓
┌──────┴──────┐
↓              ↓
Successful    Failed
   ↓           ↓
Q&A Pairs   Review Queue
   ↓           ↓
[Admin Review] → [Approve] → Knowledge Base
                         
                    Vector Index Update
                         ↓
              Improved Chatbot Responses
```

## Benefits
1. **No Manual Training** - System learns from real conversations
2. **Always Up-to-date** - Knowledge base grows daily
3. **Quality Controlled** - Admin approval required
4. **Measurable** - Track improvement over time

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Wrong info learned | Admin review required before adding |
| Repeating incorrect answers | Human approval gate |
| Knowledge base bloat | Deduplication, age-based cleanup |
| Privacy concerns | Anonymize user data |

## Implementation Priority
1. **Week 1-2**: Daily scan job + Q&A extraction
2. **Week 3**: Admin review UI for learned pairs
3. **Week 4**: Auto-approve for high-confidence extractions
4. **Week 5+**: Analytics dashboard

## Success Metrics
- % of conversations that get answered (target: >90%)
- Average conversation satisfaction score
- Number of auto-learned Q&A pairs added
- Reduction in unanswered queries over time