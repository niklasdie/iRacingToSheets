"""iRacing OAuth2 token management (password_limited grant).

Legacy email/password auth was retired 2025-12-09; the Data API now requires
OAuth2 (https://oauth.iracing.com). This module obtains and refreshes a Bearer
access token using the `password_limited` grant, which is designed for
unattended/headless clients (no browser redirect).

Requires a registered client_id/client_secret. iRacing has currently PAUSED
issuing new OAuth client IDs, so this cannot be exercised until you hold
credentials — but the implementation follows the documented spec so it is ready
the moment registration reopens.

Docs: https://oauth.iracing.com/oauth2/book/token_endpoint.html
"""
import base64
import hashlib
import json
import os
import time

import requests

TOKEN_URL = "https://oauth.iracing.com/oauth2/token"
SCOPE = "iracing.auth"
# Refresh a little before the real expiry to avoid edge-of-validity failures.
_EXPIRY_MARGIN_S = 30


def mask_secret(secret: str, identifier: str) -> str:
    """iRacing's masking: base64( sha256( secret + lower(trim(identifier)) ) ).

    `identifier` is the client_id when masking a client_secret, or the username
    (email) when masking a user password. Standard base64 alphabet + padding.
    """
    normalized_id = identifier.strip().lower()
    digest = hashlib.sha256(f"{secret}{normalized_id}".encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


class IRacingAuthError(SystemExit):
    """Raised (as a clean exit) when the token endpoint rejects the request."""


class IRacingOAuth:
    def __init__(self, client_id: str, client_secret: str, username: str,
                 password: str, token_cache_path: str | None = None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self._cache_path = token_cache_path
        self._tokens: dict = self._load_cache()

    # --- public API ---------------------------------------------------------

    def access_token(self) -> str:
        """Return a valid Bearer access token, authenticating/refreshing as needed."""
        if self._valid(self._tokens.get("access_expiry")):
            return self._tokens["access_token"]

        if self._valid(self._tokens.get("refresh_expiry")) and self._tokens.get("refresh_token"):
            try:
                self._request_tokens({
                    "grant_type": "refresh_token",
                    "refresh_token": self._tokens["refresh_token"],
                })
                return self._tokens["access_token"]
            except IRacingAuthError:
                pass  # refresh failed/expired — fall back to full login

        self._request_tokens({
            "grant_type": "password_limited",
            "username": self._username,
            "password": mask_secret(self._password, self._username),
            "scope": SCOPE,
        })
        return self._tokens["access_token"]

    def invalidate(self) -> None:
        """Force a re-auth on the next access_token() call (e.g. after a 401)."""
        self._tokens["access_expiry"] = 0

    # --- internals ----------------------------------------------------------

    def _request_tokens(self, grant_fields: dict) -> None:
        data = {
            "client_id": self._client_id,
            "client_secret": mask_secret(self._client_secret, self._client_id),
            **grant_fields,
        }
        try:
            # requests form-encodes (and percent-encodes) dict bodies for us,
            # which the masked base64 secret (+, /, =) requires.
            r = requests.post(TOKEN_URL, data=data, timeout=20)
        except requests.RequestException as e:
            raise IRacingAuthError(f"Could not reach iRacing auth server: {e}")

        try:
            body = r.json()
        except ValueError:
            raise IRacingAuthError(
                f"iRacing auth returned a non-JSON response (HTTP {r.status_code}): "
                f"{r.text[:200]}"
            )

        if r.status_code != 200 or "error" in body:
            raise IRacingAuthError(
                "iRacing OAuth2 rejected the request: "
                f"{body.get('error', r.status_code)} — "
                f"{body.get('error_description', r.text[:200])}"
            )

        now = time.time()
        self._tokens = {
            "access_token": body["access_token"],
            "access_expiry": now + body.get("expires_in", 600),
        }
        if body.get("refresh_token"):
            self._tokens["refresh_token"] = body["refresh_token"]
            self._tokens["refresh_expiry"] = now + body.get("refresh_token_expires_in", 0)
        self._save_cache()

    @staticmethod
    def _valid(expiry) -> bool:
        return bool(expiry) and time.time() < (expiry - _EXPIRY_MARGIN_S)

    def _load_cache(self) -> dict:
        if not self._cache_path or not os.path.exists(self._cache_path):
            return {}
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        if not self._cache_path:
            return
        try:
            with open(self._cache_path, "w", encoding="utf-8") as fh:
                json.dump(self._tokens, fh)
            os.chmod(self._cache_path, 0o600)
        except OSError:
            pass  # caching is a convenience, not required
