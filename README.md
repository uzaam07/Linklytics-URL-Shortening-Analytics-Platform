# Linklytics — Private Link Analytics SaaS MVP

Linklytics is a Flask + SQLite + vanilla JavaScript URL shortener with a black monochrome dashboard. This version implements the core engineering roadmap: account authentication, workspace isolation, a forward-compatible schema migration path, automated tests, basic abuse prevention, bot-filtered analytics, date ranges, custom-domain DNS verification scaffolding, plan quotas, and deployment configuration.

## 🚀 Live Demo

**Try Linklytics here:** [Linklytics — URL Shortening & Analytics Platform](https://linklytics-url-shortening-analytics.onrender.com)

Explore the application to experience its URL shortening, link management, and analytics features.

## Features

### Accounts and private workspaces
- Register, sign in, and sign out.
- Passwords stored with Werkzeug's password hashing (never plain text).
- Session cookies are HttpOnly and SameSite=Lax; secure cookies enable when `FLASK_ENV=production`.
- CSRF token validation for state-changing API routes.
- Every link, analytics query, custom domain, and deletion is scoped to the signed-in owner.
- Existing unowned links from a previous local MVP are assigned to the first account that registers, preserving local demo data.

### Links and abuse prevention
- Generated aliases and custom aliases, pause/resume, delete, copy, and CSV export.
- HTTP/HTTPS only; rejects localhost/private IP literals, local/internal hostnames, URL credentials, malformed hosts, and punycode domains by default.
- Redirect targets are read from the database and revalidated before redirecting; no request-supplied open-redirect parameter exists.
- Basic in-process per-IP rate limits for auth, API operations, link creation, and redirects.
- Bot-like user agents are recorded separately and excluded from dashboard analytics.
- Security headers and request body size limit.

### Analytics
- Select 7, 30, or 90-day ranges from the dashboard.
- Daily click trends, referrers, device category, top links, and an approximate unique-visitor count based on a keyed IP/User-Agent hash.
- The visitor count is an estimate, not a verified count of people. Update/rotate `SECRET_KEY` to invalidate old fingerprints.

## Run locally on Windows

1. Install Python 3.10+.
2. Extract the ZIP and open the folder in VS Code.
3. In the VS Code terminal:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   python app.py
   ```

4. Open http://127.0.0.1:5000 and create an account. The new database starts without sample/demo links.

If PowerShell blocks activation, use Command Prompt and run `.venv\Scripts\activate.bat`.

## Run tests

```powershell
python -m pytest -q
```

Tests cover registration, private workspaces, alias creation, redirects, analytics date ranges, CSRF enforcement, unsafe destinations, and custom-domain registration.

## Production deployment

- A Render blueprint is provided in `render.yaml`; review it before deploying and ensure the persistent disk is attached to the service.
- `wsgi.py` and `Procfile` support a WSGI server such as Gunicorn (`gunicorn wsgi:app`).
- Set a strong `SECRET_KEY`; use HTTPS and a trusted reverse proxy.
- SQLite is suitable for a low-traffic portfolio deployment. For larger multi-instance production, migrate to PostgreSQL and use a shared rate-limit store such as Redis.
- The included in-memory rate limiter is per process and resets on restart. Replace it with Redis-backed rate limiting for multiple workers/instances.
- Basic hostname validation does not replace a commercial URL reputation/phishing feed or a robust DNS-rebinding/egress policy. For public use, add reputation checks, abuse reporting, email verification, account recovery, audit logs, monitoring, backups, privacy/retention controls, and DNS/domain ownership verification procedures.
- Custom domain TXT verification is implemented, but automatic TLS certificate issuance and reverse-proxy routing are infrastructure responsibilities.
- Do not use Flask's development server or debug mode in production.

## Database migrations

The app uses `schema_migrations` and applies additive schema upgrades at startup so existing local SQLite databases can be upgraded without manually deleting them. Keep backups before production migrations. For a larger product, move to Alembic/Flask-Migrate and a migration review process.

## API overview

- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `GET/POST /api/links`, `GET /api/links/<id>`, `PATCH/DELETE /api/links/<id>`
- `GET /api/analytics?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET/POST /api/domains`, `POST /api/domains/<id>/verify`, `DELETE /api/domains/<id>`
- `GET /api/billing`, `POST /api/billing/checkout`
- `GET /api/health`

State-changing API requests require the session's `X-CSRF-Token` header.

## Added production integrations

### Stripe subscriptions (test mode first)

1. Create a recurring product/Price in the Stripe Dashboard.
2. Install the updated dependencies with `pip install -r requirements.txt`.
3. Set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, and `PUBLIC_BASE_URL` in the deployment environment. Keep all secret keys server-side and never commit them.
4. In Stripe Workbench / Developers, create a webhook pointing to `https://YOUR-DOMAIN/api/billing/webhook`. Subscribe to `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, and `invoice.payment_failed`.
5. Copy the webhook signing secret into `STRIPE_WEBHOOK_SECRET`. Test the entire subscription lifecycle in Stripe test mode before switching to live keys.
6. The Settings billing button opens hosted Stripe Checkout when configured. The signed webhook is the authority for subscription state; never change a user's plan from a client-side success redirect.

### Redis-backed rate limiting

Set `REDIS_URL` to a private Redis instance in multi-worker deployments. When configured, the app uses Redis counters shared between workers. In production, an unavailable configured Redis limiter fails closed with HTTP 429. If `REDIS_URL` is blank, the app uses an in-process limiter for local development only. Do not expose Redis publicly.

### Custom-domain TLS with Caddy

1. Add a custom domain in Settings and create the displayed TXT record at `_linklytics.YOUR-DOMAIN`.
2. Verify the TXT record in the dashboard.
3. Point the domain's A/AAAA record to the Caddy host (or configure an appropriate CNAME).
4. Install Caddy on the proxy host, adapt `Caddyfile.example`, and set `TRUST_PROXY=1` for the Flask service. Caddy's on-demand TLS `ask` endpoint checks that the requested hostname is verified before issuing a certificate.
5. Restrict access to the Flask port so public traffic goes through the trusted proxy. Confirm the DNS provider and hosting platform support the routing you configure.

Caddy on-demand TLS configuration is an example and must be reviewed for your infrastructure. Certificate issuance has rate limits; test with staging/non-production domains first. A verified TXT record alone does not point DNS at your server.

### Production readiness checklist

- Use a strong unique `SECRET_KEY`; set `FLASK_ENV=production`, `TRUST_PROXY=1` only behind a trusted proxy, and enforce HTTPS.
- Configure Redis and monitor its health if using multiple workers.
- Back up persistent data and test restores. SQLite remains intended for a small single-instance deployment; migrate to PostgreSQL before horizontal scaling.
- Configure Stripe webhooks and verify events in test mode before accepting live payments.
- Add transactional email, email verification, password reset, account deletion, audit logging, alerting, abuse-reporting and URL reputation integrations before public launch. These workflows are not represented as complete by this starter.
- Review privacy/retention rules for visitor fingerprints and click logs; the unique-visitor metric is an estimate.
