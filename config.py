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


@dataclass
class Config:
    anthropic_key: str
    google_places_key: str
    default_niche: str


CONFIG = Config(
    anthropic_key=_require("ANTHROPIC_API_KEY"),
    google_places_key=_require("GOOGLE_PLACES_KEY"),
    default_niche=os.getenv("DEFAULT_NICHE", "bathroom remodeling"),
)
