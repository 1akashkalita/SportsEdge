#!/usr/bin/env python3
"""NBA Prop Monitor - Monitors line movements from The Odds API against baseline"""

import json
import requests
import os
from datetime import datetime, timedelta
from collections import defaultdict
from openpyxl import load_workbook
from pathlib import Path

API_KEY = "[REDACTED_OLD_THE_ODDS_API_KEY]"
BASE_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

PROPS_DIR = "/Users/akashkalita/sports_picks/data/nba"

# Load fresh PrizePicks data
PRIZEPICKS_PATH = os.path.join(PROPS_DIR, "prizepicks_nba_latest.json")
BASELINE_XLSX = os.path.join(PROPS_DIR, "nba_YYYY-MM-DD.xlsx")

print("=" * 70)
print("NBA PROP LINE MONITOR")
print("=" * 70)
print(f"Running at: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}")
print()

# STEP 0: Already have fresh PrizePicks data loaded
print("[STEP 0] Fresh PrizePicks data available")
with open(PRIZEPICKS_PATH, 'r') as f:
    latest_data = json.load(f)
print(f"✓ Loaded {len(latest_data)} NBA props from PrizePicks (latest)")

# Parse fresh baseline from PrizePicks JSON
nba_props_fresh = []
for row in latest_data:
    # Skip deleted promo props - only keep active standard/standard_plus props
    status = str(row.get('status', '')).lower() if isinstance(row.get('status'), list) else str(row.get('status', '')).lower()
    is_promo_bool = getattr(row, 'isPromo', False) or row.get('is_promo', False) in [True, 'true', 1]
    
    status_clean = ''.join(map(str, row.get('status', []))).strip().lower() if isinstance(row.get('status'), list) else str(row.get('status', '')).strip().lower()
    try:
        is_deleted = 'deleted' in status_clean or (row.get('isPromo') == True and is_promo_bool)
        
        if status_clean not in ['deleted', '', None, 'none'] or row.get('status') not in [[], '']:
            nba_props_fresh.append(row)
    except:
        pass

print()
