"""iRacing Data API client (OAuth2 Bearer auth).

Replaces the legacy `iracingdataapi` library, which authenticated via the
now-removed email/password `/auth` endpoint. We call the Data API directly with
an OAuth2 Bearer token (see iracing_oauth.py) and handle the API's two quirks:

  1. Most endpoints return {"link": <presigned S3 url>}; the real payload is
     fetched from that link.
  2. Some payloads (e.g. lap data) are chunked: the payload carries a
     `chunk_info` with a base url + file names to download and concatenate.

Docs: https://oauth.iracing.com/oauth2/book/data_api_workflow.html
"""
import requests

from iracing_oauth import IRacingOAuth, IRacingAuthError

BASE_URL = "https://members-ng.iracing.com"

_OAUTH_HELP = (
    "iRacing now requires OAuth2 (legacy email/password auth was removed "
    "2025-12-09). Set IRACING_CLIENT_ID / IRACING_CLIENT_SECRET in .env. "
    "Note: iRacing has paused issuing new OAuth client IDs, so you need "
    "credentials obtained before the pause — check "
    "https://oauth.iracing.com/accountmanagement/."
)


class IRacingDataAPI:
    """Thin authenticated wrapper over the iRacing Data API."""

    def __init__(self, oauth: IRacingOAuth):
        self._oauth = oauth
        self._session = requests.Session()

    def _get(self, url: str, params: dict | None = None, auth: bool = True) -> requests.Response:
        headers = {}
        if auth:
            headers["Authorization"] = f"Bearer {self._oauth.access_token()}"
        r = self._session.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 401 and auth:
            # Token may have expired mid-run; re-auth once and retry.
            self._oauth.invalidate()
            headers["Authorization"] = f"Bearer {self._oauth.access_token()}"
            r = self._session.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        return r

    def _get_resource(self, path: str, **params):
        """GET a Data API endpoint and resolve the {'link': ...} indirection."""
        payload = self._get(BASE_URL + path, params=params).json()
        if isinstance(payload, dict) and "link" in payload:
            # The S3 link is presigned — fetch without the Bearer header.
            return self._get(payload["link"], auth=False).json()
        return payload

    def _resolve_chunks(self, payload):
        """Concatenate chunked data (e.g. lap data) into a single list."""
        info = payload.get("chunk_info") if isinstance(payload, dict) else None
        if not info or not info.get("chunk_file_names"):
            return [] if isinstance(payload, dict) else payload
        base = info.get("base_download_url", "")
        rows = []
        for name in info["chunk_file_names"]:
            rows.extend(self._get(base + name, auth=False).json())
        return rows

    # --- endpoints used by this tool ---------------------------------------

    def result(self, subsession_id: int) -> dict:
        return self._get_resource("/data/results/get", subsession_id=subsession_id)

    def stats_member_recent_races(self, cust_id: int) -> dict:
        return self._get_resource("/data/stats/member_recent_races", cust_id=cust_id)

    def result_lap_data(self, subsession_id: int, cust_id: int, simsession_number: int = 0) -> list:
        payload = self._get_resource(
            "/data/results/lap_data",
            subsession_id=subsession_id,
            simsession_number=simsession_number,
            cust_id=cust_id,
        )
        return self._resolve_chunks(payload)


class IRacingClient:
    """High-level interface used by main.py, with friendly error handling."""

    def __init__(self, client_id: str | None, client_secret: str | None,
                 email: str, password: str, token_cache_path: str | None = None):
        if email.lower().endswith("@example.com"):
            raise SystemExit(
                f"IRACING_EMAIL is still a placeholder ({email}). "
                "Set your real iRacing account email in .env."
            )
        if not client_id or not client_secret:
            raise SystemExit(_OAUTH_HELP)

        oauth = IRacingOAuth(client_id, client_secret, email, password, token_cache_path)
        self._api = IRacingDataAPI(oauth)

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except IRacingAuthError:
            raise  # already a clean, explanatory SystemExit
        except requests.HTTPError as e:
            raise SystemExit(f"iRacing Data API error: {e}\n\n{_OAUTH_HELP}")
        except requests.RequestException as e:
            raise SystemExit(f"Could not reach the iRacing Data API: {e}")

    def latest_subsession_id(self, cust_id: int) -> int:
        data = self._call(self._api.stats_member_recent_races, cust_id)
        races = data.get("races", []) if isinstance(data, dict) else (data or [])
        if not races:
            raise SystemExit(f"No recent races found for cust_id {cust_id}.")
        races = sorted(races, key=lambda r: r.get("session_start_time", ""), reverse=True)
        return int(races[0]["subsession_id"])

    def session_result(self, subsession_id: int) -> dict:
        return self._call(self._api.result, subsession_id)

    def lap_data(self, subsession_id: int, cust_id: int, simsession_number: int = 0) -> list:
        return self._call(self._api.result_lap_data, subsession_id, cust_id, simsession_number)
