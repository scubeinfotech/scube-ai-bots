# Widget Setup Help

## Overview
To add the AI chatbot widget to any website, you need to embed a small JavaScript snippet. This snippet loads the widget, authenticates it with your tenant, and injects the chat UI into the page.

## Step‑by‑Step Instructions
1. **Locate Your Embed Code**
   - In the dashboard, go to **Channels → Website Chatbot**.
   - Click **"Get Embed Code"**. The code will appear in the **Embed Code** box and is also copied to your clipboard automatically.

2. **Copy the Script Tag**
   - The snippet looks like this (your domain, tenant ID and API key will be filled in automatically):
   ```html
   <script id="scube-widget"
           src="https://YOUR_DOMAIN/static/widget.js"
           data-tenant-id="YOUR_TENANT_ID"
           data-api-key="YOUR_API_KEY"
           async></script>
   ```
   - **Do not modify the attribute names** (`id`, `src`, `data-tenant-id`, `data-api-key`).

3. **Paste Into Your Site**
   - Open the HTML source of the page(s) where you want the chatbot to appear.
   - **Place the script tag just before the closing `</body>` tag**. This ensures the widget loads after the rest of the page content.
   - Example:
   ```html
   <!DOCTYPE html>
   <html lang="en">
   <head>
       <meta charset="UTF-8">
       <title>My Site</title>
   </head>
   <body>
       <!-- Your page content -->

       <!-- Chatbot widget -->
       <script id="scube-widget"
               src="https://example.com/static/widget.js"
               data-tenant-id="12345"
               data-api-key="abcd1234efgh5678"
               async></script>
   </body>
   </html>
   ```

4. **Position the Widget (Optional)**
   - By default the widget appears in the **bottom‑right** corner.
   - You can change its position by adding a `data-position` attribute:
     ```html
     <script id="scube-widget" ... data-position="left"></script>   <!-- bottom‑left -->
     <script id="scube-widget" ... data-position="top-right"></script> <!-- top‑right -->
     ```
   - Accepted values: `right` (default), `left`, `top-right`, `top-left`.

5. **Save & Deploy**
   - Save the HTML file and deploy your site as you normally would (e.g., push to your web server, run your static site generator, etc.).
   - Open the page in a browser and you should see the chat icon appear in the chosen corner.

## Troubleshooting
- **Widget does not appear**
  - Verify the `src` URL points to a reachable domain (no 404).
  - Ensure the `data-tenant-id` and `data-api-key` are correct and not truncated.
  - Check the browser console for any JavaScript errors.
- **Chat icon is hidden**
  - Some CSS frameworks may override the widget’s default styles. Make sure no global `* { box-sizing: border-box; }` or `overflow: hidden` on the `body` is interfering.
- **Multiple widgets on the same page**
  - Only one widget per page is supported. Remove any duplicate `<script id="scube-widget">` tags.

## Need More Help?
If you run into any issues, contact our support team at **support@scubeinfotech.com.sg** or visit the **Help Center** in the dashboard.
