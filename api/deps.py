"""FastAPI shared dependencies: Supabase client and API-key auth."""
from __future__ import annotations
import os
from functools import lru_cache

from fastapi import Header, HTTPException
from supabase import create_client, Client as SupabaseClient


@lru_cache(maxsize=1)
def get_supabase() -> SupabaseClient:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def verify_api_key(x_api_key: str = Header(...)) -> None:
    """Dependency: reject requests with wrong API key."""
    if x_api_key != os.environ["VISTALINE_API_SECRET"]:
        raise HTTPException(status_code=401, detail="Invalid API key")
