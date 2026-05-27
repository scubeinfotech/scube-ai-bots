# SCUBE Infotech Widget Deployment

## ✅ 3 simple steps to deploy on scubeinfotech.com.sg

---

### Step 1: Add this widget embed code to your website footer

Put this **before `</body>`** tag on every page:

```html
<!-- SCUBE LLM Chatbot Widget -->
<script src="https://chat.scubeinfotech.com.sg/static/widget.js?v=1778207464"></script>
<script>
  LLMChatbot.init({
    apiUrl: 'https://chat.scubeinfotech.com.sg',
    tenantId: 'fb8a4ec0-e463-4678-8178-32b8332db73a',
    tokenRefreshUrl: '/get-chatbot-token'
  });
</script>
```

---

### Step 2: Create this backend endpoint on your server

Create a file named `get-chatbot-token.php` at your website root:

```php
<?php
// get-chatbot-token.php
header("Content-Type: application/json");
header("Access-Control-Allow-Origin: https://scubeinfotech.com.sg");
header("Access-Control-Allow-Credentials: true");

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

$ch = curl_init("https://chat.scubeinfotech.com.sg/api/chat/token/fb8a4ec0-e463-4678-8178-32b8332db73a");
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "X-API-Key: 7NWUNtZbYHzV4xtV0iPl2BTjSNELvR1PiCAQAWJvZik",
    "Content-Type: application/json"
]);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
    "origin" => "https://scubeinfotech.com.sg"
]));
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 5);

$response = curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

http_response_code($http_code);
echo $response;
?>
```

---

### Step 3: Verify

1. Upload both changes to your website
2. Visit scubeinfotech.com.sg
3. The chat widget will appear in the bottom right corner

✅ That is everything required. No other changes needed.
✅ Permanent API key is never exposed to browsers.
✅ Tokens automatically refresh every 12 minutes.
✅ 100% backward compatible, no changes to existing functionality.
