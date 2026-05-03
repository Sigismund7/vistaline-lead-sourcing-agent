"""Smoke: FastAPI app importable and routes registered."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app
routes = {r.path for r in app.routes}
required = [
    "/campaigns",
    "/campaigns/{campaign_id}",
    "/campaigns/{campaign_id}/events",
    "/campaigns/{campaign_id}/leads",
    "/campaigns/{campaign_id}/leads.csv",
    "/campaigns/{campaign_id}/leads/master.csv",
]
for path in required:
    assert path in routes, f"Missing route {path}. Got: {sorted(routes)}"
print("API routes OK")
