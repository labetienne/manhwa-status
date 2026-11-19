#!/usr/bin/env python3
"""Vérifie les sites de sites.json et écrit status.json (lancé par GitHub Actions)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import server

out = ROOT / "status.json"
prev = {}
if out.exists():
    try:
        prev = {s["name"]: s for s in json.loads(out.read_text())["sites"]}
    except Exception:  # noqa
        pass
data = server.check_all(force=True)
for i, s in enumerate(data["sites"]):
    if s["status"] == "blocked":  # filtre réseau : on garde le dernier statut connu
        p = prev.get(s["name"])
        data["sites"][i] = p if p and p["status"] in ("up", "down") else {**s, "status": "unknown"}
out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
print({k: sum(1 for s in data["sites"] if s["status"] == k) for k in ("up", "down", "unknown")})
