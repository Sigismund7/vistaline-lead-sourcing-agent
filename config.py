"""Centralized config — reads from .env."""
from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}. See .env.example.")
    return val


def _optional(key: str, default: str = "") -> str:
    """Return env var or default. Downstream code raises only when actually used."""
    return os.getenv(key, default)


@dataclass
class Config:
    anthropic_key: str
    google_places_key: str
    default_niche: str

    # Sourcing layer 1 — Azure Maps POI Search (universal across 50 states).
    # Empty when the operator hasn't provisioned yet; downstream code should
    # raise RuntimeError when actually constructing the client.
    azure_maps_key: str = ""

    # Sourcing layer 2 — Yelp Fusion API. Free-tier ceiling is 5000 calls/day;
    # see docs/plan-tightening-v1.md operator-side mitigations 5-6.
    yelp_fusion_key: str = ""

    # Sourcing layer 3 — Brave Web Search (used by agents/website_finder.py).
    # Free tier is 2000 queries/month with $5/mo credits applied; see
    # docs/plan-tightening-v1.md. Budget guard below is the operator-side
    # defense-in-depth complement to the dashboard cap.
    brave_search_key: str = ""

    # ---- Rate limiting (Mitigation 10) ----
    azure_maps_rate_limit_qps: float = 1.5
    azure_maps_jitter_ms: int = 200
    yelp_rate_limit_qps: float = 1.0
    yelp_jitter_ms: int = 300
    brave_rate_limit_qps: float = 1.0
    brave_jitter_ms: int = 200

    # ---- Brave budget guard (defense-in-depth with dashboard cap) ----
    brave_max_monthly_queries: int = 2000
    brave_budget_state_dir: str = "state"  # state/brave_budget_<YYYY-MM>.json

    # ---- Throttle handling (Mitigation 13) ----
    api_max_retries: int = 5
    api_backoff_base_s: float = 1.0
    api_backoff_max_s: float = 60.0
    api_request_timeout_s: int = 30

    # ---- Source-search radius / limits ----
    azure_maps_default_radius_m: int = 25000
    yelp_default_radius_m: int = 25000


CONFIG = Config(
    anthropic_key=_require("ANTHROPIC_API_KEY"),
    google_places_key=_require("GOOGLE_PLACES_KEY"),
    default_niche=os.getenv("DEFAULT_NICHE", "bathroom remodeling"),
    azure_maps_key=_optional("AZURE_MAPS_KEY"),
    yelp_fusion_key=_optional("YELP_FUSION_KEY"),
    brave_search_key=_optional("BRAVE_SEARCH_KEY"),
)
