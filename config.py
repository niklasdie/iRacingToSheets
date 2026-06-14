"""Loads configuration and secrets from the environment (.env).

The active pipeline reads local `.ibt` telemetry files, which need no iRacing
credentials. The iRacing OAuth fields are kept (optional) only for the
alternative web `/data` API path in iracing_client.py.
"""
from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass
class Config:
    # Google Sheets (required for upload)
    google_creds_path: str
    google_sheet_id: str | None
    google_share_email: str | None
    # Local telemetry
    telemetry_dir: str
    # iRacing web Data API (optional — alternative path only)
    iracing_email: str | None
    iracing_password: str | None
    iracing_cust_id: int | None
    iracing_client_id: str | None
    iracing_client_secret: str | None
    token_cache_path: str


def _clean(name: str) -> str | None:
    return (os.getenv(name) or "").strip() or None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value and value.strip() else None


def load_config() -> Config:
    return Config(
        google_creds_path=os.getenv("GOOGLE_CREDENTIALS_PATH", "service_account.json"),
        google_sheet_id=_clean("GOOGLE_SHEET_ID"),
        google_share_email=_clean("GOOGLE_SHARE_EMAIL"),
        telemetry_dir=os.getenv("IRACING_TELEMETRY_DIR", "~/Documents/iRacing/telemetry"),
        iracing_email=_clean("IRACING_EMAIL"),
        iracing_password=_clean("IRACING_PASSWORD"),
        iracing_cust_id=_int_or_none(os.getenv("IRACING_CUST_ID")),
        iracing_client_id=_clean("IRACING_CLIENT_ID"),
        iracing_client_secret=_clean("IRACING_CLIENT_SECRET"),
        token_cache_path=os.getenv("IRACING_TOKEN_CACHE", ".iracing_tokens.json"),
    )
