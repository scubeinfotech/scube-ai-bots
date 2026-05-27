# 🚀 Quick Start: Get Rapas Live with Real LLM (FREE!)

**Time Required:** 10-15 minutes  
**Cost:** $0 (using Groq free tier)  
**Resources:** ~1 GB RAM

---

## ✅ Prerequisites (Already Done!)

- ✓ Platform built and tested
- ✓ All 17 tests passing
- ✓ Groq adapter added
- ✓ Rapas seed script ready

---

## 🎯 Step-by-Step Setup

### **Step 1: Get Free Groq API Key** (3 minutes)

1. Visit: **https://console.groq.com**
2. Click "Sign Up" (free, no credit card needed)
3. Verify your email
4. Go to "API Keys" section
5. Click "Create API Key"
6. Copy the key (starts with `gsk_...`)

💡 **Groq Free Tier Benefits:**
- 14,400 requests/day (very generous!)
- Fastest LLM inference in the market
- Perfect for 5 small business websites
- No credit card required

---

### **Step 2: Configure Environment** (2 minutes)

```bash
cd /home/sudhakar/New-Projects/centralized-llm-platform/backend

# Copy example environment file
cp .env.example .env

# Edit the file
nano .env
```

**Update these lines:**
```bash
# Change from mock to groq
LLM_PROVIDER=groq

# Add your API key (replace with actual key)
GROQ_API_KEY=gsk_your_actual_key_here
```

**Save and exit:** `Ctrl+X`, then `Y`, then `Enter`

---

### **Step 3: Create Rapas Tenant** (1 minute)

```bash
cd /home/sudhakar/New-Projects/centralized-llm-platform

# Run the seed script
PYTHONPATH=./backend python3 backend/seed_rapas_tenant.py
```

**Expected Output:**
```
============================================================
Rapas Tenant Seeding Script
============================================================

✓ Successfully created Rapas tenant!
  ID: <tenant-id-here>
  Name: Rapas Marine Engineering
  Slug: rapas
  Domain: rapas.com
  Model: llama-3.1-8b-instant
  Temperature: 0.3
  Max Tokens: 800

✓ Rapas is ready to use!
  Tenant ID for API calls: <tenant-id-here>
```

**Copy the Tenant ID** - you'll need it for testing!

---

### **Step 4: Start Backend** (1 minute)

```bash
cd /home/sudhakar/New-Projects/centralized-llm-platform/backend

# Activate virtual environment if you have one
# source venv/bin/activate

# Start the server
uvicorn app.main:app --reload --port 8001 --host 0.0.0.0
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

Keep this terminal open! ✓

---

### **Step 5: Test with Real LLM** (5 minutes)

#### **Option A: Test via API** (Recommended)

Open a **new terminal**:

```bash
# Replace <TENANT_ID> with your actual Rapas tenant ID from Step 3
TENANT_ID="<your-tenant-id-here>"

# Send a test message
curl -X POST "http://localhost:8001/api/chat/message/${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "What is marine propulsion and what types are commonly used?",
    "user_id": "test-user-001"
  }'
```

**You should get a real AI response!** 🎉

Example response:
```json
{
  "id": "...",
  "session_id": "...",
  "content": "Marine propulsion refers to the mechanism that generates...",
  "role": "assistant",
  "model_used": "llama-3.1-8b-instant",
  "latency_ms": 450,
  "tokens_used": 120
}
```

#### **Option B: Test via Widget**

1. Edit `widget/test.html`:
   ```javascript
   LLMChatbot.init({
       apiUrl: 'http://localhost:8001',
       tenantId: '<your-tenant-id-here>',  // Update this!
       theme: {
           primaryColor: '#0066cc',
           backgroundColor: '#ffffff'
       }
   });
   ```

2. Open in browser:
   ```bash
   # Open widget/test.html
   firefox widget/test.html  # or chrome widget/test.html
   ```

3. Click the chat button and ask: *"What marine services does Rapas provide?"*

---

## ✅ Verification Checklist

After setup, verify:

- [ ] Backend running on http://localhost:8001
- [ ] API docs accessible at http://localhost:8001/docs
- [ ] Rapas tenant created (check with: `curl http://localhost:8001/api/tenants/slug/rapas`)
- [ ] Real LLM responses received
- [ ] Widget displays and responds
- [ ] Conversation history works

---

## 🎨 Next: Customize for Rapas

### **Update Widget Styling**

Edit `widget/test.html` to match Rapas brand:

```javascript
LLMChatbot.init({
    apiUrl: 'http://localhost:8001',
    tenantId: '<your-rapas-tenant-id>',
    theme: {
        primaryColor: '#003366',      // Rapas navy blue
        backgroundColor: '#ffffff',
        textColor: '#1f2937'
    }
});
```

### **Add to Rapas Website**

Add this to your Rapas website `<head>`:

```html
<!-- LLM Chatbot Widget -->
<script src="https://your-domain.com/widget/widget.js"></script>
<script>
    LLMChatbot.init({
        apiUrl: 'https://your-api-domain.com',
        tenantId: '<your-rapas-tenant-id>',
        apiKey: '<optional-api-key>',
        theme: {
            primaryColor: '#003366',
            backgroundColor: '#ffffff'
        }
    });
</script>
```

---

## 🔧 Troubleshooting

### **Issue: "Groq API returned 401"**
**Solution:** Check your API key in `.env` file

### **Issue: "Tenant not found"**
**Solution:** Run seed script again or verify tenant ID

### **Issue: "Connection refused"**
**Solution:** Make sure backend is running on port 8001

### **Issue: "Module not found"**
**Solution:** Run from project root with `PYTHONPATH=./backend`

---

## 📊 What You've Achieved

✅ **FREE Production-Ready LLM Platform**
- Real AI responses (not mock data)
- 14,400 requests/day capacity
- Fast response times (<1 second)
- Professional marine engineering assistant
- Ready for real traffic

✅ **Cost: $0** for months of operation

✅ **Resources: ~1 GB RAM** (very efficient!)

---

## 🎯 What's Next?

### **Short Term (This Week)**
1. Test Rapas conversations thoroughly
2. Fine-tune prompts if needed
3. Deploy widget on Rapas website
4. Monitor usage and quality

### **Medium Term (Weeks 3-4)**
1. Create SDSFoodz tenant (food/business)
2. Customize prompts for restaurant industry
3. Test cross-domain functionality

### **Long Term (Weeks 5-8)**
1. Onboard all 5 tenants
2. Build admin dashboard
3. Add analytics and monitoring
4. Launch production

---

## 💡 Pro Tips

1. **Test different questions** to see how the marine engineering context works
2. **Monitor token usage** in API responses
3. **Adjust temperature** in Rapas config (lower = more precise, higher = more creative)
4. **Check Groq dashboard** to see your usage stats

---

## 🆘 Need Help?

- **API Docs:** http://localhost:8001/docs
- **Groq Console:** https://console.groq.com
- **Architecture Review:** See `ARCHITECTURE_REVIEW.md`
- **Full Docs:** See `DEVELOPERS.md`

---

**You're now running a production-ready LLM platform for FREE! 🎉**

No Ollama needed. No heavy resources. Just fast, smart responses.

Time to ship! 🚀
