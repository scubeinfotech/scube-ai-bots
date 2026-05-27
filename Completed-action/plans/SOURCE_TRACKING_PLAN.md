# Source Tracking for Admin Portal - Implementation Plan

## Overview
Track and display which knowledge sources were used for each AI response, visible only in the admin portal for improvement planning.

## Current State
- Sources are retrieved from vector knowledge search
- Currently hidden from end users (just implemented)
- Sources stored in message metadata but not exposed in UI

## Requirements
1. **Hide from users**: ✅ Sources not shown in chat widget
2. **Admin view**: Show sources in admin portal for each message
3. **Analytics**: Track which sources are most used
4. **Improvement insights**: Identify gaps in knowledge base

## Implementation Tasks

### Phase 1: API Enhancement
- [ ] Create new API endpoint: `GET /api/admin/chat/{tenant_id}/messages` with sources
- [ ] Add `include_sources` query parameter
- [ ] Return retrieved_sources in response

### Phase 2: Admin Dashboard Updates
- [ ] Add "Sources" column to chat history table
- [ ] Show source names and relevance scores
- [ ] Add expandable row for full source details

### Phase 3: Analytics Dashboard
- [ ] Track most frequently used sources
- [ ] Identify sources with low relevance scores
- [ ] Suggest knowledge base improvements

## Technical Details

### Database Changes
- Sources already stored in `ChatMessage.msg_metadata`
- No schema changes needed

### API Response Example
```json
{
  "messages": [
    {
      "id": "msg-123",
      "content": "We offer IT support services...",
      "role": "assistant",
      "sources": [
        {"source_name": "Services Page", "score": 0.85},
        {"source_name": "FAQ", "score": 0.72}
      ]
    }
  ]
}
```

## Priority
**Medium** - Useful for knowledge base management and continuous improvement
