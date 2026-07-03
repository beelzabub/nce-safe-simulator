"""Server-side authentication gate (epic #135, issue #157).

Dispatches on the config ``auth.method``:

- ``"none"`` (default when unset) — no enforcement; the UI keeps its
  cosmetic client-side front door. Preserves pre-gate deployments.
- ``"basic"`` — every request must authenticate. Dev-only hardcoded
  credential; real AAA methods (pki-cac, oidc, saml, ldap, local) plug
  their own values into this dispatch later.

Two ways to authenticate when a method is active:
- the session cookie issued by ``POST /api/auth/login``, or
- an ``Authorization: Basic`` header (curl/API/Grafana access).

The unauthenticated surface is exactly what the login page needs to render:
the SPA shell and its built assets, the login/session/logout endpoints, the
background imagery, and the curated ``GET /api/config``.
"""

import base64
import hmac
import secrets
import time

from server.auth_backgrounds import load_auth_config

# DEV ONLY — throwaway credential for auth.method "basic". Never a real
# secret; real mechanisms arrive with the AAA method issues (#152-#156).
_DEV_BASIC_USERNAME = "asdf"
_DEV_BASIC_PASSWORD = "asdf"

SESSION_COOKIE = "nce_session"
_SESSION_TTL_SECONDS = 12 * 3600

# In-memory session store {token: expiry}. Fine for the dev "basic" method —
# sessions don't survive a server restart, which is acceptable front-door
# behavior; real AAA methods bring their own session/token semantics.
_sessions = {}


def auth_method(gl=None):
    method = load_auth_config(gl).get("method", "none")
    return method if isinstance(method, str) and method else "none"


def verify_credentials(username, password):
    """Constant-time check of the dev basic credential."""
    user_ok = hmac.compare_digest(str(username or ""), _DEV_BASIC_USERNAME)
    pass_ok = hmac.compare_digest(str(password or ""), _DEV_BASIC_PASSWORD)
    return user_ok and pass_ok


# ── Sessions ────────────────────────────────────────────────────────────────

def create_session():
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _SESSION_TTL_SECONDS
    return token


def session_valid(token):
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None:
        return False
    if time.time() >= expiry:
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token):
    _sessions.pop(token, None)


# ── Request checks ──────────────────────────────────────────────────────────

def _basic_header_ok(authorization):
    if not authorization or not authorization.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return False
    return verify_credentials(username, password)


def request_authenticated(cookies, headers):
    """True if a session cookie or Basic header authenticates this request."""
    if session_valid(cookies.get(SESSION_COOKIE)):
        return True
    return _basic_header_ok(headers.get("authorization"))


def is_public_path(method, path):
    """The surface the login page itself needs — everything else is gated.

    Note /api/auth/session and /api/auth/logout are deliberately public: the
    router guard probes the session before authenticating, and logout must
    never 401 on an already-dead session.
    """
    if path == "/" and method in ("GET", "HEAD"):
        return True
    if path == "/app" or path.startswith("/app/"):
        return method in ("GET", "HEAD")
    if path == "/api/auth/login":
        return method == "POST"
    if path == "/api/auth/logout":
        return method == "POST"
    if path == "/api/auth/session" and method in ("GET", "HEAD"):
        return True
    if (path == "/api/auth/backgrounds" or path.startswith("/api/auth/backgrounds/")) \
            and method in ("GET", "HEAD"):
        return True
    if path == "/api/config" and method in ("GET", "HEAD"):
        return True
    return False


def gate_check(gl, method, path, cookies, headers):
    """Return True if the request may proceed."""
    if auth_method(gl) == "none":
        return True
    if is_public_path(method, path):
        return True
    return request_authenticated(cookies, headers)
