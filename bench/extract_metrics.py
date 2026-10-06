#!/usr/bin/env python3
"""Extract per-session cost/token metrics from a sandbox home's opencode DB.
Usage: extract_metrics.py DB_PATH OUT_JSON NAME"""
import sqlite3, json, sys

db = sqlite3.connect(sys.argv[1])
rows = list(db.execute(
    "SELECT id, cost, tokens_input, tokens_output, tokens_reasoning, model, time_created "
    "FROM session_v2"))
sessions = [{"id": r[0], "cost": r[1], "tokens_in": r[2], "tokens_out": r[3],
             "tokens_reasoning": r[4],
             "model": (json.loads(r[5]) if r[5] else {}).get("id"),
             "variant": (json.loads(r[5]) if r[5] else {}).get("variant"),
             "started": r[6]} for r in rows]
json.dump({"name": sys.argv[3], "sessions": sessions}, open(sys.argv[2], "w"), indent=1)
