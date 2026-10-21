"""Linklytics: multi-user URL shortener and analytics SaaS starter.

Use HTTPS, a trusted reverse proxy, persistent storage, Redis for shared rate
limiting, and a configured payment provider before accepting public traffic.
"""
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import socket
import sqlite3
import string
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get("LINKLYTICS_DATABASE", os.path.join(BASE_DIR, "linklytics.db"))
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-secret-before-deployment"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    MAX_CONTENT_LENGTH=32 * 1024,
    JSON_SORT_KEYS=False,
)
# Enable only when the app is behind a trusted proxy (e.g. Caddy or Render).
if os.environ.get("TRUST_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
FREE_LINK_LIMIT = 100
FREE_MONTHLY_CLICK_LIMIT = 10000
RATE_WINDOW_SECONDS = 60
RATE_LIMITS = {"auth": (10, 60), "create": (20, 60), "general": (180, 60), "redirect": (120, 60)}
_rate_events = defaultdict(deque)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        plan TEXT NOT NULL DEFAULT 'free' CHECK(plan IN ('free','pro')),
        created_at TEXT NOT NULL,
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        subscription_status TEXT NOT NULL DEFAULT 'none'
      );
      CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        original_url TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE
      );
      CREATE TABLE IF NOT EXISTS clicks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
        clicked_at TEXT NOT NULL,
        referrer TEXT NOT NULL DEFAULT 'Direct',
        device TEXT NOT NULL DEFAULT 'Desktop',
        is_bot INTEGER NOT NULL DEFAULT 0,
        visitor_hash TEXT
      );
      CREATE TABLE IF NOT EXISTS custom_domains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        domain TEXT NOT NULL UNIQUE COLLATE NOCASE,
        verification_token TEXT NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_clicks_link_id ON clicks(link_id);
      CREATE INDEX IF NOT EXISTS idx_clicks_clicked_at ON clicks(clicked_at);
    """)
    # Lightweight forward migrations for databases created by earlier versions.
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    for column, declaration in (
        ("stripe_customer_id", "TEXT"),
        ("stripe_subscription_id", "TEXT"),
        ("subscription_status", "TEXT NOT NULL DEFAULT 'none'"),
    ):
        if column not in user_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {declaration}")
    link_cols = {r["name"] for r in conn.execute("PRAGMA table_info(links)")}
    if "owner_id" not in link_cols:
        conn.execute("ALTER TABLE links ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
    click_cols = {r["name"] for r in conn.execute("PRAGMA table_info(clicks)")}
    if "is_bot" not in click_cols:
        conn.execute("ALTER TABLE clicks ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0")
    if "visitor_hash" not in click_cols:
        conn.execute("ALTER TABLE clicks ADD COLUMN visitor_hash TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_links_owner_id ON links(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clicks_bot_time ON clicks(is_bot, clicked_at)")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, ?)", (now_iso(),))
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (2, ?)", (now_iso(),))
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (3, ?)", (now_iso(),))
    conn.commit()
    conn.close()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db().execute("SELECT id, email, name, plan, created_at FROM users WHERE id = ?", (uid,)).fetchone()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.context_processor
def inject_template_values():
    return {"csrf_token": csrf_token, "user": current_user()}


def json_error(message, status):
    return jsonify({"error": message}), status


def rate_limit_bucket():
    path = request.path
    if path in ("/login", "/register", "/api/auth/login", "/api/auth/register"):
        return "auth", RATE_LIMITS["auth"]
    if request.method == "POST" and path == "/api/links":
        return "create", RATE_LIMITS["create"]
    if re.fullmatch(r"/[A-Za-z0-9_-]{3,24}", path):
        return "redirect", RATE_LIMITS["redirect"]
    return "general", RATE_LIMITS["general"]


@app.before_request
def security_and_rate_limit():
    bucket, (limit, window) = rate_limit_bucket()
    ip = request.remote_addr or "unknown"
    if not consume_rate_limit(bucket, ip, limit, window):
        return json_error("Too many requests. Please wait and try again.", 429) if request.path.startswith("/api/") else ("Too many requests. Please try again shortly.", 429)
    is_stripe_webhook = request.path == "/api/billing/webhook"
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.path.startswith("/api/") and not request.path.startswith("/api/auth/") and not is_stripe_webhook:
        expected = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            return json_error("Security token expired. Refresh the page and try again.", 400)


def consume_rate_limit(bucket, ip, limit, window):
    """Use Redis across workers when configured, with local dev fallback."""
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        try:
            import redis
            client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
            key = f"linklytics:rl:{bucket}:{ip}"
            count = client.incr(key)
            if count == 1:
                client.expire(key, window)
            return count <= limit
        except Exception:
            if os.environ.get("FLASK_ENV") == "production":
                app.logger.exception("Redis rate limiter unavailable")
                return False
            app.logger.warning("Redis rate limiter unavailable; using in-process fallback")
    key = (bucket, ip)
    now = time.time()
    events = _rate_events[key]
    while events and events[0] <= now - window:
        events.popleft()
    if len(events) >= limit:
        return False
    events.append(now)
    return True


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def require_user():
    user = current_user()
    if user is None:
        return None, (json_error("Please sign in to continue.", 401))
    return user, None


def valid_http_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlparse(value.strip())
        host = parsed.hostname
        if parsed.scheme.lower() not in ("http", "https") or not host or not parsed.netloc:
            return False
        if parsed.username or parsed.password or any(ch.isspace() for ch in host):
            return False
        host = host.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal", ".test")):
            return False
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
            if not ip.is_global:
                return False
        except ValueError:
            if "." not in host or host.startswith(".") or host.endswith("."):
                return False
            # Conservative default: reject punycode hostnames to reduce homograph phishing risk.
            if any(label.startswith("xn--") for label in host.split(".")):
                return False
            if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split(".")):
                return False
        return True
    except (ValueError, UnicodeError):
        return False


def is_bot(user_agent):
    ua = (user_agent or "").lower()
    bot_terms = ("bot", "crawler", "spider", "preview", "slackbot", "facebookexternalhit", "whatsapp", "discordbot", "telegrambot", "headless")
    return not ua.strip() or any(term in ua for term in bot_terms)


def visitor_fingerprint():
    # Keyed pseudonymous estimate; it is not a verified person-level identity.
    # Rotating SECRET_KEY changes fingerprints, which limits long-term linkability.
    ip = request.remote_addr or "unknown"
    ua = request.headers.get("User-Agent", "")[:300]
    secret = app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(secret, f"{ip}|{ua}".encode(), hashlib.sha256).hexdigest()[:32]


def make_code(length=6):
    alphabet = string.ascii_letters + string.digits
    conn = db()
    for _ in range(10):
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not conn.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
            return code
    raise RuntimeError("Could not generate a unique short code. Please try again.")


def link_dict(row):
    base_url = request.host_url.rstrip("/")
    owner_id = row["owner_id"] if "owner_id" in row.keys() else None
    if owner_id:
        custom = db().execute("SELECT domain FROM custom_domains WHERE user_id=? AND verified=1 ORDER BY id LIMIT 1", (owner_id,)).fetchone()
        if custom:
            base_url = f"{request.scheme}://{custom['domain']}"
    return {
        "id": row["id"], "code": row["code"],
        "short_url": base_url + "/" + row["code"],
        "original_url": row["original_url"], "title": row["title"],
        "created_at": row["created_at"], "is_active": bool(row["is_active"]),
        "clicks": row["clicks"] if "clicks" in row.keys() else 0,
    }


def owned_link(link_id, user_id):
    return db().execute("SELECT * FROM links WHERE id = ? AND owner_id = ?", (link_id, user_id)).fetchone()


@app.get("/")
def index():
    if not current_user():
        return render_template("auth.html")
    return render_template("index.html")


@app.post("/api/auth/register")
def register():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()[:80]
    email = str(payload.get("email", "")).strip().lower()[:254]
    password = str(payload.get("password", ""))
    if len(name) < 2:
        return json_error("Enter your name (at least 2 characters).", 400)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return json_error("Enter a valid email address.", 400)
    if len(password) < 10 or len(password) > 128:
        return json_error("Password must be 10–128 characters long.", 400)
    conn = db()
    try:
        cur = conn.execute("INSERT INTO users(email,name,password_hash,created_at) VALUES(?,?,?,?)", (email, name, generate_password_hash(password), now_iso()))
        user_id = cur.lastrowid
        # Preserve legacy local-demo links by assigning unowned records to the first account.
        conn.execute("UPDATE links SET owner_id = ? WHERE owner_id IS NULL", (user_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        return json_error("An account with that email already exists.", 409)
    session.clear()
    session["user_id"] = user_id
    csrf_token()
    return jsonify({"ok": True, "user": {"name": name, "email": email}}), 201


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    user = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return json_error("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    csrf_token()
    return jsonify({"ok": True, "user": {"name": user["name"], "email": user["email"]}})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/me")
def auth_me():
    user = current_user()
    if not user:
        return json_error("Not signed in.", 401)
    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"], "plan": user["plan"]})


@app.get("/api/links")
def list_links():
    user, error = require_user()
    if error: return error
    rows = db().execute("""SELECT l.*, COUNT(c.id) AS clicks FROM links l
      LEFT JOIN clicks c ON c.link_id=l.id AND c.is_bot=0 WHERE l.owner_id=?
      GROUP BY l.id ORDER BY l.id DESC""", (user["id"],)).fetchall()
    return jsonify([link_dict(row) for row in rows])


@app.post("/api/links")
def create_link():
    user, error = require_user()
    if error: return error
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()[:80]
    original_url = str(payload.get("original_url", "")).strip()
    requested_code = str(payload.get("custom_code", "")).strip()
    if not valid_http_url(original_url):
        return json_error("Enter a public HTTP(S) destination. Local/private hosts and unsupported URLs are blocked.", 400)
    if not title: title = urlparse(original_url).hostname or "Untitled link"
    if requested_code and not re.fullmatch(r"[A-Za-z0-9_-]{3,24}", requested_code):
        return json_error("Custom aliases must be 3–24 characters (letters, numbers, _ or -).", 400)
    conn = db()
    if user["plan"] == "free":
        used = conn.execute("SELECT COUNT(*) FROM links WHERE owner_id=?", (user["id"],)).fetchone()[0]
        if used >= FREE_LINK_LIMIT:
            return json_error(f"Free plan limit reached ({FREE_LINK_LIMIT} links). Upgrade your plan to create more.", 402)
    code = requested_code or make_code()
    try:
        cur = conn.execute("INSERT INTO links(code,original_url,title,created_at,owner_id) VALUES(?,?,?,?,?)", (code, original_url, title, now_iso(), user["id"]))
        conn.commit()
    except sqlite3.IntegrityError:
        return json_error("That alias is already taken. Try another one.", 409)
    row = conn.execute("SELECT l.*,0 AS clicks FROM links l WHERE l.id=?", (cur.lastrowid,)).fetchone()
    return jsonify(link_dict(row)), 201


def analytics_query(user_id, link_id=None):
    conn = db()
    start_arg = request.args.get("start")
    end_arg = request.args.get("end")
    try:
        end_date = datetime.fromisoformat(end_arg).date() if end_arg else datetime.now(timezone.utc).date()
        start_date = datetime.fromisoformat(start_arg).date() if start_arg else end_date - timedelta(days=6)
    except ValueError:
        return None, json_error("Dates must use YYYY-MM-DD format.", 400)
    if start_date > end_date or (end_date - start_date).days > 365:
        return None, json_error("Choose a valid date range of up to 366 days.", 400)
    link_filter = " AND l.id = ?" if link_id is not None else ""
    params = [user_id, start_date.isoformat(), (end_date + timedelta(days=1)).isoformat()]
    if link_id is not None: params.append(link_id)
    click_where = "l.owner_id=? AND c.is_bot=0 AND c.clicked_at>=? AND c.clicked_at<?" + link_filter
    range_clicks = conn.execute(f"SELECT COUNT(*) FROM clicks c JOIN links l ON l.id=c.link_id WHERE {click_where}", params).fetchone()[0]
    total_clicks = conn.execute("SELECT COUNT(*) FROM clicks c JOIN links l ON l.id=c.link_id WHERE l.owner_id=? AND c.is_bot=0", (user_id,)).fetchone()[0]
    visitors = conn.execute(f"SELECT COUNT(DISTINCT c.visitor_hash) FROM clicks c JOIN links l ON l.id=c.link_id WHERE {click_where} AND c.visitor_hash IS NOT NULL", params).fetchone()[0]
    today = datetime.now(timezone.utc).date().isoformat()
    today_params = [user_id, today, (datetime.fromisoformat(today).date()+timedelta(days=1)).isoformat()]
    if link_id is not None: today_params.append(link_id)
    today_clicks = conn.execute(f"SELECT COUNT(*) FROM clicks c JOIN links l ON l.id=c.link_id WHERE l.owner_id=? AND c.is_bot=0 AND c.clicked_at>=? AND c.clicked_at<?" + (" AND l.id=?" if link_id is not None else ""), today_params).fetchone()[0]
    total_links = conn.execute("SELECT COUNT(*) FROM links WHERE owner_id=?", (user_id,)).fetchone()[0]
    active_links = conn.execute("SELECT COUNT(*) FROM links WHERE owner_id=? AND is_active=1", (user_id,)).fetchone()[0]
    daily_rows = conn.execute(f"SELECT substr(c.clicked_at,1,10) AS day, COUNT(*) AS count FROM clicks c JOIN links l ON l.id=c.link_id WHERE {click_where} GROUP BY day ORDER BY day", params).fetchall()
    daily_map = {r["day"]: r["count"] for r in daily_rows}
    daily = [{"day": (start_date + timedelta(days=i)).isoformat(), "count": daily_map.get((start_date + timedelta(days=i)).isoformat(), 0)} for i in range((end_date-start_date).days+1)]
    refs = conn.execute(f"SELECT c.referrer AS name, COUNT(*) AS count FROM clicks c JOIN links l ON l.id=c.link_id WHERE {click_where} GROUP BY c.referrer ORDER BY count DESC LIMIT 8", params).fetchall()
    devices = conn.execute(f"SELECT c.device AS name, COUNT(*) AS count FROM clicks c JOIN links l ON l.id=c.link_id WHERE {click_where} GROUP BY c.device ORDER BY count DESC", params).fetchall()
    top_links = conn.execute(f"SELECT l.code,l.title,COUNT(c.id) AS clicks FROM links l LEFT JOIN clicks c ON c.link_id=l.id AND c.is_bot=0 AND c.clicked_at>=? AND c.clicked_at<? WHERE l.owner_id=?" + (" AND l.id=?" if link_id is not None else "") + " GROUP BY l.id ORDER BY clicks DESC LIMIT 5", [start_date.isoformat(), (end_date+timedelta(days=1)).isoformat(), user_id] + ([link_id] if link_id is not None else [])).fetchall()
    return {"total_links": total_links, "active_links": active_links, "total_clicks": total_clicks, "range_clicks": range_clicks, "today_clicks": today_clicks,
            "unique_visitors_estimate": visitors, "start": start_date.isoformat(), "end": end_date.isoformat(), "daily": daily,
            "referrers": [dict(r) for r in refs], "devices": [dict(r) for r in devices], "top_links": [dict(r) for r in top_links]}, None


@app.get("/api/analytics")
def analytics():
    user, error = require_user()
    if error: return error
    result, error = analytics_query(user["id"])
    return error or jsonify(result)


@app.get("/api/links/<int:link_id>")
def link_detail(link_id):
    user, error = require_user()
    if error: return error
    row = db().execute("SELECT l.*, COUNT(CASE WHEN c.is_bot=0 THEN c.id END) AS clicks FROM links l LEFT JOIN clicks c ON c.link_id=l.id WHERE l.id=? AND l.owner_id=? GROUP BY l.id", (link_id,user["id"])).fetchone()
    if not row: return json_error("Link not found.", 404)
    data, error = analytics_query(user["id"], link_id)
    if error: return error
    return jsonify({"link": link_dict(row), "daily": data["daily"], "referrers": data["referrers"], "unique_visitors_estimate": data["unique_visitors_estimate"]})


@app.patch("/api/links/<int:link_id>")
def update_link(link_id):
    user, error = require_user()
    if error: return error
    payload = request.get_json(silent=True) or {}
    active = payload.get("is_active")
    if not isinstance(active, bool): return json_error("Provide is_active as true or false.", 400)
    cur = db().execute("UPDATE links SET is_active=? WHERE id=? AND owner_id=?", (int(active),link_id,user["id"]))
    db().commit()
    if not cur.rowcount: return json_error("Link not found.", 404)
    return jsonify({"ok": True, "is_active": active})


@app.delete("/api/links/<int:link_id>")
def delete_link(link_id):
    user, error = require_user()
    if error: return error
    cur = db().execute("DELETE FROM links WHERE id=? AND owner_id=?", (link_id,user["id"]))
    db().commit()
    if not cur.rowcount: return json_error("Link not found.", 404)
    return jsonify({"ok": True})


@app.get("/api/domains")
def list_domains():
    user, error = require_user()
    if error: return error
    rows = db().execute("SELECT id,domain,verification_token,verified,created_at FROM custom_domains WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/domains/allow-tls")
def allow_custom_domain_tls():
    """Caddy on-demand TLS authorization endpoint; only verified domains pass."""
    domain = str(request.args.get("domain", "")).strip().lower().rstrip(".")
    if not domain or len(domain) > 253:
        return ("invalid domain", 400)
    row = db().execute("SELECT 1 FROM custom_domains WHERE domain=? AND verified=1", (domain,)).fetchone()
    return ("approved", 200) if row else ("domain not verified", 403)


@app.post("/api/domains")
def add_domain():
    user, error = require_user()
    if error: return error
    payload = request.get_json(silent=True) or {}
    domain = str(payload.get("domain", "")).strip().lower().rstrip(".")
    if len(domain) > 253 or not re.fullmatch(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        return json_error("Enter a valid domain name, without http:// or a path.", 400)
    token = "linklytics-verify=" + secrets.token_urlsafe(20)
    try:
        cur = db().execute("INSERT INTO custom_domains(user_id,domain,verification_token,created_at) VALUES(?,?,?,?)", (user["id"],domain,token,now_iso()))
        db().commit()
    except sqlite3.IntegrityError:
        return json_error("That domain is already registered.", 409)
    return jsonify({"id":cur.lastrowid,"domain":domain,"verification_token":token,"verified":False,"instructions":"Add this exact TXT value to _linklytics."+domain+". Domain routing is not activated until DNS verification and production proxy configuration are completed."}), 201


@app.post("/api/domains/<int:domain_id>/verify")
def verify_domain(domain_id):
    user, error = require_user()
    if error: return error
    domain = db().execute("SELECT * FROM custom_domains WHERE id=? AND user_id=?", (domain_id,user["id"])).fetchone()
    if not domain: return json_error("Domain not found.",404)
    try:
        import dns.resolver
        answers = dns.resolver.resolve("_linklytics." + domain["domain"], "TXT", lifetime=4)
        values = []
        for answer in answers:
            values.append("".join(part.decode("utf-8") if isinstance(part, bytes) else str(part) for part in answer.strings))
        if domain["verification_token"] not in values:
            return json_error("The expected TXT record was not found yet. DNS changes may take time to propagate.", 400)
    except ImportError:
        return json_error("DNS verification dependency is missing. Install requirements.txt and retry.", 500)
    except Exception:
        return json_error("Could not find the verification TXT record yet. Check the record name/value and DNS propagation.", 400)
    db().execute("UPDATE custom_domains SET verified=1 WHERE id=? AND user_id=?", (domain_id,user["id"]))
    db().commit()
    return jsonify({"ok":True,"verified":True,"domain":domain["domain"],"note":"Ensure your DNS A/AAAA or CNAME and production reverse proxy point this domain to this Linklytics deployment."})


@app.delete("/api/domains/<int:domain_id>")
def remove_domain(domain_id):
    user, error = require_user()
    if error: return error
    cur = db().execute("DELETE FROM custom_domains WHERE id=? AND user_id=?", (domain_id,user["id"]))
    db().commit()
    if not cur.rowcount: return json_error("Domain not found.",404)
    return jsonify({"ok":True})


@app.get("/api/billing")
def billing():
    user, error = require_user()
    if error: return error
    conn = db()
    account = conn.execute("SELECT plan,subscription_status FROM users WHERE id=?", (user["id"],)).fetchone()
    links_used = conn.execute("SELECT COUNT(*) FROM links WHERE owner_id=?", (user["id"],)).fetchone()[0]
    month = datetime.now(timezone.utc).date().replace(day=1).isoformat()
    clicks_used = conn.execute("SELECT COUNT(*) FROM clicks c JOIN links l ON l.id=c.link_id WHERE l.owner_id=? AND c.is_bot=0 AND c.clicked_at>=?", (user["id"],month)).fetchone()[0]
    configured = all(os.environ.get(k) for k in ("STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "STRIPE_WEBHOOK_SECRET"))
    return jsonify({"plan":account["plan"],"links_used":links_used,"links_limit":FREE_LINK_LIMIT if account["plan"]=="free" else None,"clicks_used":clicks_used,"clicks_limit":FREE_MONTHLY_CLICK_LIMIT if account["plan"]=="free" else None,"billing_status":account["subscription_status"],"checkout_configured":bool(configured),"message":"Stripe checkout is configured." if configured else "Add Stripe API, price, and webhook keys to enable real checkout."})


@app.post("/api/billing/checkout")
def billing_checkout():
    user, error = require_user()
    if error: return error
    if not all(os.environ.get(k) for k in ("STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "STRIPE_WEBHOOK_SECRET")):
        return json_error("Billing is not configured. Add Stripe API, price, and webhook keys first.", 501)
    try:
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        account = db().execute("SELECT stripe_customer_id,email FROM users WHERE id=?", (user["id"],)).fetchone()
        customer_id = account["stripe_customer_id"]
        if not customer_id:
            customer = stripe.Customer.create(email=account["email"], metadata={"linklytics_user_id": str(user["id"])})
            customer_id = customer.id
            db().execute("UPDATE users SET stripe_customer_id=? WHERE id=?", (customer_id,user["id"]))
            db().commit()
        base = os.environ.get("PUBLIC_BASE_URL", request.host_url.rstrip("/"))
        checkout = stripe.checkout.Session.create(
            mode="subscription", customer=customer_id,
            line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
            success_url=os.environ.get("STRIPE_SUCCESS_URL", base + "/?billing=success"),
            cancel_url=os.environ.get("STRIPE_CANCEL_URL", base + "/?billing=cancelled"),
            client_reference_id=str(user["id"]),
            metadata={"linklytics_user_id": str(user["id"])},
            subscription_data={"metadata": {"linklytics_user_id": str(user["id"])}},
        )
        return jsonify({"ok": True, "checkout_url": checkout.url})
    except ImportError:
        return json_error("Stripe SDK is missing. Install project requirements and restart.", 500)
    except Exception:
        app.logger.exception("Stripe checkout session creation failed")
        return json_error("Unable to start checkout. Check Stripe configuration and server logs.", 502)


@app.post("/api/billing/webhook")
def stripe_webhook():
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not secret or not api_key:
        return json_error("Stripe webhook is not configured.", 503)
    signature = request.headers.get("Stripe-Signature", "")
    try:
        import stripe
        stripe.api_key = api_key
        event = stripe.Webhook.construct_event(request.get_data(), signature, secret)
    except ImportError:
        return json_error("Stripe SDK is missing.", 500)
    except Exception:
        return json_error("Invalid Stripe webhook signature or payload.", 400)
    obj = event.get("data", {}).get("object", {})
    event_type = event.get("type", "")
    metadata = obj.get("metadata", {}) or {}
    user_id = metadata.get("linklytics_user_id") or obj.get("client_reference_id")
    if not user_id and obj.get("customer"):
        row = db().execute("SELECT id FROM users WHERE stripe_customer_id=?", (obj.get("customer"),)).fetchone()
        user_id = str(row["id"]) if row else None
    if user_id and str(user_id).isdigit():
        uid = int(user_id)
        if event_type == "checkout.session.completed":
            paid = obj.get("payment_status") in ("paid", "no_payment_required")
            db().execute("UPDATE users SET stripe_customer_id=COALESCE(?,stripe_customer_id), stripe_subscription_id=?, plan=?, subscription_status=? WHERE id=?", (obj.get("customer"),obj.get("subscription"),"pro" if paid else "free","active" if paid else "pending",uid))
        elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
            status = obj.get("status", "canceled")
            active = status in ("active", "trialing") and event_type != "customer.subscription.deleted"
            db().execute("UPDATE users SET plan=?, subscription_status=?, stripe_subscription_id=? WHERE id=?", ("pro" if active else "free",status,obj.get("id"),uid))
        elif event_type == "invoice.payment_failed":
            db().execute("UPDATE users SET subscription_status='past_due' WHERE id=?", (uid,))
        db().commit()
    return jsonify({"received": True})


@app.get("/<code>")
def resolve_link(code):
    if code in ("favicon.ico", "robots.txt", "static"): return ("",404)
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,24}", code): return render_template("not_found.html"),404
    row = db().execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    if row is None: return render_template("not_found.html"),404
    if not row["is_active"]: return render_template("not_found.html",inactive=True),410
    destination = row["original_url"]
    # Validate again at redirect time; never accept a redirect destination from request parameters.
    if not valid_http_url(destination): return render_template("not_found.html"),410
    referrer = "Direct"
    referer_header = request.headers.get("Referer", "")
    if referer_header:
        host = urlparse(referer_header).hostname
        referrer = (host or "Other")[:253].lower()
    ua = request.headers.get("User-Agent", "")[:500]
    low_ua = ua.lower()
    device = "Mobile" if any(x in low_ua for x in ("mobile","android","iphone")) else ("Tablet" if any(x in low_ua for x in ("ipad","tablet")) else "Desktop")
    bot = is_bot(ua)
    owner = db().execute("SELECT u.id,u.plan FROM users u WHERE u.id=?", (row["owner_id"],)).fetchone() if row["owner_id"] else None
    record_analytics = True
    if owner and owner["plan"] == "free" and not bot:
        month_start = datetime.now(timezone.utc).date().replace(day=1).isoformat()
        used = db().execute("SELECT COUNT(*) FROM clicks c JOIN links l ON l.id=c.link_id WHERE l.owner_id=? AND c.is_bot=0 AND c.clicked_at>=?", (owner["id"],month_start)).fetchone()[0]
        record_analytics = used < FREE_MONTHLY_CLICK_LIMIT
    if record_analytics:
        db().execute("INSERT INTO clicks(link_id,clicked_at,referrer,device,is_bot,visitor_hash) VALUES(?,?,?,?,?,?)", (row["id"],now_iso(),referrer,device,int(bot),visitor_fingerprint()))
        db().commit()
    return redirect(destination, code=302)


@app.get("/api/health")
def health():
    return jsonify({"status":"ok","service":"Linklytics API","version":"2.0"})


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))
