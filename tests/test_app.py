from conftest import csrf


def test_home_shows_auth_when_logged_out(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Create an account" in response.data


def test_register_and_private_workspace(client):
    r = client.post("/api/auth/register", json={"name":"Alice User", "email":"alice@example.com", "password":"strong-password-123"})
    assert r.status_code == 201
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/links").get_json() == []


def test_password_minimum_and_duplicate_email(client):
    r = client.post("/api/auth/register", json={"name":"Alice User", "email":"alice@example.com", "password":"short"})
    assert r.status_code == 400
    assert client.post("/api/auth/register", json={"name":"Alice User", "email":"alice@example.com", "password":"strong-password-123"}).status_code == 201
    assert client.post("/api/auth/register", json={"name":"Alice User", "email":"alice@example.com", "password":"strong-password-123"}).status_code == 409


def test_link_create_alias_redirect_and_analytics(client, signed_in):
    headers = {"X-CSRF-Token": csrf(client)}
    r = client.post("/api/links", json={"original_url":"https://example.com/path", "title":"Example", "custom_code":"my-example"}, headers=headers)
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["code"] == "my-example"
    redirect = client.get("/my-example", headers={"User-Agent":"Mozilla/5.0 Chrome"}, follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["Location"] == "https://example.com/path"
    analytics = client.get("/api/analytics?start=2026-10-09&end=2026-10-15")
    assert analytics.status_code == 200
    assert analytics.get_json()["total_clicks"] >= 1


def test_reject_private_and_non_http_destinations(client, signed_in):
    headers = {"X-CSRF-Token": csrf(client)}
    for url in ["javascript:alert(1)", "http://localhost/admin", "http://127.0.0.1/", "https://service.local/path"]:
        r = client.post("/api/links", json={"original_url":url}, headers=headers)
        assert r.status_code == 400, (url, r.get_json())



def test_owner_isolation(client):
    # Register Alice and establish her authenticated session.
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Alice User",
            "email": "alice@example.com",
            "password": "strong-password-123"
        }
    )
    assert response.status_code == 201, response.get_json()

    headers = {"X-CSRF-Token": csrf(client)}

    # Alice creates a link.
    response = client.post(
        "/api/links",
        json={
            "original_url": "https://example.com",
            "custom_code": "alice-link"
        },
        headers=headers
    )
    assert response.status_code == 201, response.get_json()

    # Alice logs out.
    response = client.post("/api/auth/logout")
    assert response.status_code in (200, 204), response.get_data(as_text=True)

    # Bob registers and gets a separate authenticated session.
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Bob User",
            "email": "bob@example.com",
            "password": "another-secure-password"
        }
    )
    assert response.status_code == 201, response.get_json()

    # Bob must not see Alice's links.
    assert client.get("/api/links").get_json() == []

    # Bob must not access Alice's link.
    assert client.get("/api/links/1").status_code == 404



def test_mutations_require_csrf(client, signed_in):
    r = client.post("/api/links", json={"original_url":"https://example.com"})
    assert r.status_code == 400


def test_range_validation(client, signed_in):
    assert client.get("/api/analytics?start=bad&end=2026-01-01").status_code == 400
    assert client.get("/api/analytics?start=2026-02-01&end=2026-01-01").status_code == 400


def test_custom_domain_registration(client, signed_in):
    headers = {"X-CSRF-Token": csrf(client)}
    r = client.post("/api/domains", json={"domain":"links.example.com"}, headers=headers)
    assert r.status_code == 201
    assert r.get_json()["verification_token"].startswith("linklytics-verify=")
    assert client.get("/api/domains").get_json()[0]["verified"] == 0


def test_billing_is_explicitly_disabled_without_stripe_config(client, signed_in, monkeypatch):
    for key in ("STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "STRIPE_WEBHOOK_SECRET"):
        monkeypatch.delenv(key, raising=False)
    headers = {"X-CSRF-Token": csrf(client)}
    response = client.post("/api/billing/checkout", json={}, headers=headers)
    assert response.status_code == 501
    assert "not configured" in response.get_json()["error"].lower()


def test_caddy_tls_authorization_requires_verified_domain(client, signed_in):
    headers = {"X-CSRF-Token": csrf(client)}
    added = client.post("/api/domains", json={"domain":"links.example.com"}, headers=headers)
    assert added.status_code == 201
    assert client.get("/api/domains/allow-tls?domain=links.example.com").status_code == 403
    clientlytics = __import__("app")
    with clientlytics.app.app_context():
        clientlytics.db().execute("UPDATE custom_domains SET verified=1 WHERE domain=?", ("links.example.com",))
        clientlytics.db().commit()
    assert client.get("/api/domains/allow-tls?domain=links.example.com").status_code == 200
