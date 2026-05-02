"""Campaign state — single object that flows through every agent.

State is auto-persisted to disk after each step. If anything crashes,
resume by passing --resume <campaign_id> to run.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import json
import uuid


STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(exist_ok=True)


@dataclass
class Lead:
    """One lead as it evolves through the pipeline.

    Sourcer fills:    business_name, phone, website, address, area_code, domain, place_id
    Lead filter fills: kept, reject_reason
    Owner researcher fills: owner_full_name, owner_first, owner_last, owner_source, email (if found in Phase 1)
    """
    business_name: str = ""
    phone: str = ""
    website: str = ""
    address: str = ""
    area_code: str = ""
    domain: str = ""
    place_id: str = ""
    kept: bool = True
    reject_reason: str = ""
    owner_full_name: str = ""
    owner_first: str = ""
    owner_last: str = ""
    owner_source: str = ""
    email: str = ""


@dataclass
class CampaignState:
    campaign_id: str
    city: str = ""
    state_abbr: str = ""
    niche: str = ""
    target_count: int = 50
    leads: list[Lead] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def path(self) -> Path:
        return STATE_DIR / f"{self.campaign_id}.json"

    def save(self) -> None:
        self.path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, campaign_id: str) -> "CampaignState":
        path = STATE_DIR / f"{campaign_id}.json"
        data = json.loads(path.read_text())
        data["leads"] = [Lead(**l) for l in data.get("leads", [])]
        return cls(**data)

    @classmethod
    def new(cls) -> "CampaignState":
        return cls(campaign_id=datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])

    def info(self, agent: str, message: str, **fields) -> None:
        entry = {"ts": datetime.utcnow().isoformat(), "agent": agent, "msg": message, **fields}
        self.log.append(entry)
        print(f"[{agent}] {message}" + (f"  {fields}" if fields else ""))

    def mark_done(self, step: str) -> None:
        if step not in self.completed_steps:
            self.completed_steps.append(step)
        self.save()

    def is_done(self, step: str) -> bool:
        return step in self.completed_steps
