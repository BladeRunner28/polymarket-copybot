#!/usr/bin/env python3
"""Report an agent's status to the CopyBot dashboard.

Usage:
    INTERNAL_API_SECRET=... python3 scripts/report_agent_state.py

The dashboard URL defaults to http://localhost:3000 — override with
COPYBOT_DASHBOARD_URL if the server runs elsewhere (e.g. :3013 or Vercel).
"""
import os

import requests

BASE_URL = os.environ.get("COPYBOT_DASHBOARD_URL", "http://localhost:3000")

resp = requests.post(
    f"{BASE_URL}/api/agents/state",
    headers={"Authorization": f"Bearer {os.environ['INTERNAL_API_SECRET']}"},
    json={
        "id": "my-content-agent",
        "name": "Content Writer",
        "emoji": "✍️",
        "role": "Content",
        "status": "working",
        "currentTask": "Drafting thread about agent workflows",
        "tasksCompleted": 42,
        "totalCost": 3.14,
    },
    timeout=10,
)
resp.raise_for_status()
print(resp.status_code, resp.json())
