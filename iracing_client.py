"""Thin wrapper around the iRacing Data API (via the iracingdataapi library).

The library handles login (the hashed-password auth dance) and the
"follow the S3 link" indirection that the Data API uses, so we just expose
the few calls this script needs.
"""
from iracingdataapi.client import irDataClient


class IRacingClient:
    def __init__(self, email: str, password: str):
        # The library hashes the password and keeps an authenticated session.
        self._idc = irDataClient(username=email, password=password)

    def latest_subsession_id(self, cust_id: int) -> int:
        """Subsession id of the member's most recent race."""
        data = self._idc.stats_member_recent_races(cust_id=cust_id)
        races = data.get("races", []) if isinstance(data, dict) else (data or [])
        if not races:
            raise SystemExit(f"No recent races found for cust_id {cust_id}.")
        races = sorted(races, key=lambda r: r.get("session_start_time", ""), reverse=True)
        return int(races[0]["subsession_id"])

    def session_result(self, subsession_id: int) -> dict:
        """Full result document for a subsession (all sim-sessions + drivers)."""
        return self._idc.result(subsession_id=subsession_id)

    def lap_data(self, subsession_id: int, cust_id: int, simsession_number: int = 0) -> list:
        """Lap-by-lap data for one driver in one sim-session."""
        return self._idc.result_lap_data(
            subsession_id=subsession_id,
            cust_id=cust_id,
            simsession_number=simsession_number,
        )
