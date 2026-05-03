"""Verify CampaignState public interface is intact after Supabase rewrite."""
from state import CampaignState, Lead
import inspect, dataclasses

# Lead fields
lead = Lead(business_name="Acme Remodeling", phone="4075550100")
assert lead.business_name == "Acme Remodeling"
assert lead.kept == True
assert lead.email == ""

# Required methods
required_methods = ["save", "load", "new", "info", "mark_done", "is_done", "save_leads"]
for m in required_methods:
    assert hasattr(CampaignState, m), f"Missing method: {m}"

# Required fields
fields = {f.name for f in dataclasses.fields(CampaignState)}
for f in ["status", "triggered_by", "campaign_id", "city", "state_abbr", "niche",
          "target_count", "leads", "log", "completed_steps", "created_at"]:
    assert f in fields, f"Missing field: {f}"

print("Interface OK")
