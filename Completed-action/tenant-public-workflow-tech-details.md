# Centralized LLM Platform: Tenant-Facing Route Workflow & Technical Reference

## Workflow Overview

1. **Frontend (Tenant Access):**
   - Tenants access all dashboard features via `/public/*` routes:
     - `/public/login` — Login page
     - `/public/dashboard` — Main dashboard
     - `/public/conversations` — Unified chat/conversation view
     - `/public/leads` — WhatsApp leads & reservations
     - `/public/session/{session_id}` — Chat session transcript

2. **Session Handling:**
   - Session tokens are stored in `localStorage` (e.g., `tenant_token`).
   - All API calls requiring authentication send the token as `Authorization: Bearer <token>`.
   - Logout and session expiry always redirect to `/public/login`.

3. **Navigation:**
   - All navigation links and redirects use `/public/*` routes (never `/tenant/*`).
   - Legacy `/tenant/*` routes remain as aliases for backward compatibility but are not used in UI.

4. **Widget Integration:**
   - Tenants can view and copy their widget code from the dashboard.
   - Widget code is fetched via `/api/tenants/{tenant_id}/widget-code` with the correct Authorization header.

## Technical Details

### Backend (FastAPI)
- Static HTML files are located in `backend/static/` (e.g., `tenant-dashboard.html`, `tenant-conversations.html`, etc.).
- Docker and volume mounts ensure `backend/static` is available as `/app/static` inside the container.
- All `/public/*` routes serve the corresponding HTML files from `/app/static`.
- Example route handler:
  ```python
  STATIC_DIR = Path(__file__).parent.parent.resolve() / "static"
  @app.get("/public/dashboard")
  async def public_dashboard_page():
      tenant_dashboard_path = STATIC_DIR / "tenant-dashboard.html"
      if tenant_dashboard_path.exists():
          return _serve_html_no_cache(tenant_dashboard_path)
      return {"error": "Tenant dashboard page not found"}
  ```
- All `/public/*` routes return HTTP 200 and the correct HTML page if the file exists.

### Docker & Deployment
- The backend service mounts `./backend:/app` so `static` is always available as `/app/static`.
- Always test endpoints on the mapped port (e.g., 8001).
- After code or static file changes, rebuild the image and restart services:
  ```sh
  docker-compose build api
  ./service-control.sh restart
  ```

### Troubleshooting
- If `/public/*` routes return 404:
  - Confirm static files exist in `backend/static` locally and `/app/static` in the container.
  - Check port mapping (use 8001 if mapped).
  - Review container logs for errors.
- Use `curl -si http://localhost:8001/public/dashboard` to verify route health.

## Best Practices
- Always use `/public/*` for tenant-facing routes and navigation.
- Keep static files under version control.
- Document any changes to routing or static file structure.
- Test after every deployment or code change.

---

_Last updated: May 22, 2026_