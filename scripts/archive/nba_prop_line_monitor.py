#!/usr/bin/env python3
"""
NBA PROP LINE MONITOR WORKFLOW
- Fetches fresh PrizePicks data (current baseline)
- Pulls current lines from The Odds API (basketball_nba endpoint)
- Compares against baseline morning picks from yesterday's date
- Calculates line movements
- Flags any props that moved 0.5+ points favorably
- Detects arbitrages and injury watches for disappeared props
- Generates summary report with counts of active/skipped/injury props

NO TELEGRAM - output to stdout only
"""

import json
import requests
from datetime import datetime, date
from collections import defaultdict
from pathlib import Path

# API Configuration  
API_KEY="[REDACTED_OLD_THE_ODDS_API_KEY]"  
BASE_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

# Workspace Path
WORKSPACE_PATH = "/Users/akashkalita/sports_picks"
ODDS_DIR = WORKSPACE_PATH + "/data/nba"

print("=" * 80)
print("NBA PROP LINE MONITOR WORKFLOW")
print("=" * 80)
now = datetime.now()
YESTERDAY_DATE = date.today().isoformat()
TIMESTAMP = now.strftime("%Y-%m-%d %H:%M:%S")
print(f"\nRunning at: {now.strftime('%H:%M UTC')} | Date: {TIMESTAMP}")
print()

# ========================================
# STEP 0: LOAD FRESHEST PRIZEPICKS DATA FIRST  
# ========================================
print("[STEP 0] Loading freshest PrizePicks data (current baseline)...")

pp_data = None
for filename in [ODDS_DIR+"/prizepicks_nba_latest.json",
                 ODDS_DIR+"/prizepicks_nba_all_2026-06-08.json"]:
    try:
        with open(filename, "r") as f:
            pp_data = json.load(f)
        print(f"  Loaded from: {filename}")
        print(f"  Total props available: {len(pp_data)}")
        break
    except FileNotFoundError:
        continue
    
if pp_data is None:
    print("ERROR: Could not find PrizePicks data file")
    exit(1)

print()
