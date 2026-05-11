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

    # Owner Researcher Phase 3 — OpenCorporates API for business ownership lookup.
    # Requires paid API key. Empty when not provisioned; downstream code should
    # raise RuntimeError when actually constructing the client.
    opencorporates_api_key: str = ""

    # Owner Researcher Phase 0 — ScraperAPI proxy for Yelp profile pages.
    # Yelp's Cloudflare protection blocks headless browsers; ScraperAPI's
    # premium tier (10 credits/req) handles the bypass. Empty when not
    # provisioned; yelp_profile.py silently disables Phase 0 in that case.
    scraperapi_key: str = ""

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

    # ---- ScraperAPI rate + budget guard ----
    # Hobby plan is 100k credits/mo; Yelp pages cost 10 credits each at
    # premium tier, so 10k credits ≈ 1000 Yelp pages.
    scraperapi_rate_limit_qps: float = 5.0
    scraperapi_jitter_ms: int = 100
    scraperapi_max_monthly_credits: int = 10000
    scraperapi_request_timeout_s: int = 70  # premium tier can take 30-60s

    # ---- Throttle handling (Mitigation 13) ----
    api_max_retries: int = 5
    api_backoff_base_s: float = 1.0
    api_backoff_max_s: float = 60.0
    api_request_timeout_s: int = 30

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    vistaline_api_secret: str = ""

    # ---- Source-search radius / limits ----
    azure_maps_default_radius_m: int = 25000
    yelp_default_radius_m: int = 25000

    # ---- Sourcer cross-source dedup ----
    # rapidfuzz token_sort_ratio threshold above which two leads from
    # different sources are considered duplicates and merged. Default 85
    # is conservative — calibrate during smoke testing if needed.
    dedup_match_threshold: int = 85

    # ---- Cross-run dedup cache ----
    # Leads seen for this city+state within ttl_days are skipped on re-sourcing.
    leads_cache_ttl_days: int = 30

    # ---- Personalizer (post-FindyMail X/Y + LinkedIn) ----
    personalizer_max_parallel: int = 4
    personalizer_vision_model: str = "claude-sonnet-4-20250514"
    personalizer_screenshot_timeout_s: int = 25

    # ---- BBB Phase 0 ----
    # Compare mode: run both bbb_direct (HTTP+ScraperAPI scrape) and
    # bbb_websearch (Claude web_search constrained to bbb.org) on every kept
    # lead so we can A/B their hit rates side-by-side. Flip to False once we
    # pick a winner and prune the other module.
    bbb_compare_mode: bool = True
    bbb_direct_enabled: bool = True
    bbb_websearch_enabled: bool = True
    # Optional pre-phase. Off by default; flip on for segments where Yelp
    # listings are reliably claimed (the labeled Business Owner field is
    # only populated on claimed pages).
    yelp_phase0_enabled: bool = False


CONFIG = Config(
    anthropic_key=_require("ANTHROPIC_API_KEY"),
    google_places_key=_require("GOOGLE_PLACES_KEY"),
    default_niche=os.getenv("DEFAULT_NICHE", "bathroom remodeling"),
    azure_maps_key=_optional("AZURE_MAPS_KEY"),
    yelp_fusion_key=_optional("YELP_FUSION_KEY"),
    brave_search_key=_optional("BRAVE_SEARCH_KEY"),
    opencorporates_api_key=_optional("OPENCORPORATES_API_KEY"),
    scraperapi_key=_optional("SCRAPERAPI_KEY"),
    supabase_url=_optional("SUPABASE_URL"),
    supabase_service_role_key=_optional("SUPABASE_SERVICE_ROLE_KEY"),
    vistaline_api_secret=_optional("VISTALINE_API_SECRET"),
)
