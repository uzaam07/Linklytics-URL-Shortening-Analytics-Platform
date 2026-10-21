import os
import sys
import tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_fd, _test_db = tempfile.mkstemp(prefix="linklytics-tests-", suffix=".db")
os.close(_fd)

os.environ["LINKLYTICS_DATABASE"] = _test_db
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough"

import app as linklytics_app

@pytest.fixture()
def client():
    linklytics_app.DATABASE = _test_db
    linklytics_app.app.config.update(TESTING=True, SECRET_KEY="test-secret-key-that-is-long-enough")
    linklytics_app._rate_events.clear()
    if os.path.exists(_test_db):
        os.remove(_test_db)
    linklytics_app.init_db()
    with linklytics_app.app.test_client() as client:
        yield client

@pytest.fixture()
def signed_in(client):
    response = client.post("/api/auth/register", json={"name":"Test User", "email":"test@example.com", "password":"very-secure-password"})
    assert response.status_code == 201, response.get_json()
    return client


def csrf(client):
    # Trigger the application's template context processor, which creates
    # a CSRF token in the session through csrf_token().
    client.get("/")

    with client.session_transaction() as sess:
        token = sess.get("csrf_token", "")

    assert token, "CSRF token was not created by GET /"
    return token


@pytest.fixture()
def csrf_headers():
    return csrf
