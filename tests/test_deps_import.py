"""Smoke test: new deps importable after pip install."""
import importlib, sys

for mod in ["supabase", "fastapi", "uvicorn"]:
    try:
        importlib.import_module(mod)
        print(f"OK  {mod}")
    except ImportError as e:
        print(f"FAIL {mod}: {e}")
        sys.exit(1)

print("All deps OK")
