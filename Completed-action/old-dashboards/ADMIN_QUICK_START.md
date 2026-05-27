# Admin Dashboard - Quick Start Guide

## 🚀 Getting Started

### 1. Make Sure Backend is Running
```bash
cd /home/sudhakar/New-Projects/centralized-llm-platform/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### 2. Open Admin Dashboard
```
http://127.0.0.1:8001/admin
```

### 3. Login
**Default Credentials:**
- Username: `admin`
- Password: `admin123`

---

## 📊 Dashboard Overview

After login, you'll see 4 main tabs:

### Tab 1: Analytics Dashboard
Shows real-time metrics for all customers:
- Total active tenants count
- Average engagement rate across all customers
- Average conversion rate
- Average unanswered questions rate
- Charts comparing customer performance
- Detailed table with all metrics

### Tab 2: Manage Tenants
Create and manage customer accounts:
- **View Existing:** List of all active tenants
- **Add New Tenant:** Click "+ Add Tenant" button
  - Enter tenant name (e.g., "ScubaInfo Tech")
  - Slug (URL-safe, e.g., "scubeinfo")
  - Domain (e.g., "scubeinfotech.com.sg")
  - Select LLM model
  - System will generate unique tenant ID
- **Edit:** Update configuration for existing tenant
- **Delete:** Deactivate customer account

### Tab 3: Agreements
Manage service agreements and contracts:
- Create service agreements linked to customers
- Track agreement type:
  - `service` → Standard service agreement
  - `sla` → Service Level Agreement
  - `maintenance` → Maintenance contract
- Set contract dates and terms
- Monitor agreement status (active/expired/pending)

### Tab 4: Maintenance
Operational tools for tenant support:
- View tenant health status
- See knowledge base item counts:
  - **Products:** Customer's product/service list
  - **Services:** Available services
  - **FAQs:** Frequently asked questions
- Update knowledge base (click "Edit Knowledge")
- Monitor all customer configurations

---

## 📝 Common Tasks

### Create a New Customer (Tenant)
```
1. Click "Manage Tenants" tab
2. Click "+ Add Tenant" button
3. Fill in form:
   - Name: "Your Company"
   - Slug: "your-company" (no spaces, lowercase)
   - Domain: "your-company.com"
   - Model: "llama-3.1-8b-instant"
4. Click "Create"
5. Tenant is now ready for chat embeddings!
```

### Update Customer's Knowledge Base
```
1. Go to "Maintenance" tab
2. Find customer in the list
3. Click "Edit Knowledge" button
4. Add products/services as JSON:
   {
     "name": "Product Name",
     "aliases": ["alias1", "alias2"],
     "description": "What it does"
   }
5. Submit - changes live immediately!
```

### Track Customer Performance
```
1. Go to "Analytics Dashboard" tab
2. Look at the performance table
3. Color-coded metrics:
   - 🟢 Green (0-5%) = Excellent
   - 🟡 Yellow (5-15%) = Good
   - 🔴 Red (>15%) = Needs attention
4. Unanswered rate > 10% = Time to update knowledge base
```

### Create Service Agreement
```
1. Go to "Agreements" tab
2. Click "+ New Agreement"
3. Select customer from dropdown
4. Fill in:
   - Agreement Name: "SDS Foods Service Agreement"
   - Type: "service"
   - Start Date: Today
   - End Date: 1 year from today
   - Terms: (optional) Service terms
5. Click "Create"
6. Agreement tracked in system
```

---

## 📊 Understanding the Metrics

| Metric | What It Means | Good Range |
|--------|---------------|-----------|
| **Engagement Rate** | % of user messages that mention products | >15% |
| **Conversion Rate** | % of product-interested sessions with CTA | >35% |
| **Unanswered Rate** | % of bot responses that couldn't help | <10% |
| **Fallback Rate** | % of generic fallback responses | <5% |
| **Error Rate** | % of LLM request failures | <1% |
| **Latency** | Average response time in ms | <1000ms |

---

## 🔒 Security Notes

- **Keep credentials secret!** Change default admin password in production
- **Token expires in 24 hours** - you'll need to log back in
- **Clear browser cache** if login issues occur
- **Use HTTPS** in production (not HTTP)

---

## 🆘 Troubleshooting

### "Invalid credentials" error
- Check username/password (case-sensitive)
- Make sure backend is running (`uvicorn` command)
- Clear localStorage: Press F12 → Application → Clear all

### Dashboard loads but no data
- Check if backend API is reachable
- Open browser console (F12) for error messages
- Verify `/api/analytics/summary` endpoint works:
  ```bash
  curl "http://127.0.0.1:8001/api/analytics/summary?days=7"
  ```

### Can't add new tenant
- Ensure slug is unique (no duplicates)
- Slug must be URL-safe (lowercase, hyphens only)
- Check browser console for error details

### Tenant changes not showing in chat
- Changes are live immediately
- New conversations will use updated config
- Existing sessions won't be affected (design choice)

---

## 🎯 Pro Tips

1. **Batch Updates:** Create all new customers first, then set up their knowledge bases
2. **Knowledge Base:** Use clear, specific product names for better bot understanding
3. **Monitoring:** Check "Maintenance" tab weekly to update underperforming tenants
4. **Agreements:** Set automatic reminders for renewal dates (external calendar)
5. **Testing:** Create test tenant with slug "test-tenant" before production use

---

## 📞 API Endpoints (for direct integration)

All endpoints require `Authorization: Bearer {token}` header after login.

```bash
# Login
POST /api/admin/login
Body: {"username": "admin", "password": "admin123"}
Response: {"access_token": "jwt_token", ...}

# Create Tenant
POST /api/admin/tenants
Body: {
  "name": "Company Name",
  "slug": "company-slug",
  "domain": "company.com",
  "model_name": "llama-3.1-8b-instant"
}

# List Tenants
GET /api/admin/tenants
Header: Authorization: Bearer {token}

# Update Tenant
PUT /api/admin/tenants/{tenant_id}
Body: {"name": "New Name", "prompt_template": "..."}

# Create Agreement
POST /api/admin/agreements
Body: {
  "tenant_id": "id",
  "agreement_name": "Agreement Name",
  "agreement_type": "service",
  "start_date": "2026-03-09T00:00:00Z",
  "end_date": "2027-03-09T00:00:00Z"
}
```

---

**Version:** 1.0  
**Last Updated:** March 9, 2026  
**Status:** ✅ Production Ready
