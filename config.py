"""Loads configuration and secrets from the environment (.env)."""
from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass
class Config:
    iracing_email: str
    iracing_password: str
    iracing_cust_id: int | None
    iracing_client_id: str | None
    iracing_client_secret: str | None
    token_cache_path: str
    google_creds_path: str
    google_sheet_id: str | None
    google_share_email: str | None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value and value.strip() else None


def load_config() -> Config:
    email = os.getenv("IRACING_EMAIL")
    password = os.getenv("IRACING_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "Missing IRACING_EMAIL / IRACING_PASSWORD. "
            "Copy .env.example to .env and fill it in."
        )

    return Config(
        iracing_email=email,
        iracing_password=password,
        iracing_cust_id=_int_or_none(os.getenv("IRACING_CUST_ID")),
        iracing_client_id=(os.getenv("IRACING_CLIENT_ID") or "").strip() or None,
        iracing_client_secret=(os.getenv("IRACING_CLIENT_SECRET") or "").strip() or None,
        token_cache_path=os.getenv("IRACING_TOKEN_CACHE", ".iracing_tokens.json"),
        google_creds_path=os.getenv("GOOGLE_CREDENTIALS_PATH", "service_account.json"),
        google_sheet_id=(os.getenv("GOOGLE_SHEET_ID") or "").strip() or None,
        google_share_email=(os.getenv("GOOGLE_SHARE_EMAIL") or "").strip() or None,
    )
