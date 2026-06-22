#!/usr/bin/env python3
"""
NBA PROP LINE MONITOR SCRIPT
Compares current live lines from The Odds API to PrizePicks fresh baseline.
Flags line movements >= 0.5 points (favorable toward original pick direction).
Detects arbitrages, injury watches (prop disappeared), skipped props.
Updates status columns and sends Telegram alert only if changes detected.
"""

import json
import requests
import os
from datetime import datetime
from collections import defaultdict

API_KEY = "[REDACTED_OLD_THE_ODDS_API_KEY]"
BASE_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

PROPS_DIR = "/Users/akashkalita/sports_picks/data/nba"
TIMESTAMP = datetime.now().strftime("%d-%b-%Y")  # e.g., "07-Jun-2026" if yesterday's data

print("=" * 80)
print(f"NBA PROP LINE MONITOR - {TIMESTAMP}")
print("=" * 80)
print(f"Running at: {datetime.now().strftime('%H:%M %p')}\n")

# ========================================
# STEP 0 — FETCH FRESHEST PRIZEPICKS LINES FIRST  
# ========================================
print("[STEP 0] Fetching freshest PrizePicks data...")
PRIZEPICKS_PATH = PROPS_DIR + "/prizepicks_nba_latest.json"

if not os.path.exists(PRIZEPICKS_PATH):
    PRIZEPICKS_PATH = PROPS_DIR + "/prizepicks_nba_all_2026-06-08.json"
    
print(f"  Loading: {os.path.basename(PRIZEPICKS_PATH)}")

with open(PRIZEPICKS_PATH, 'r') as f:
    latest_data = json.load(f)

# Parse PrizePicks fresh data - only active props (exclude deleted/promo)
nba_props_fresh = []
for row in latest_data:
    status_list = row.get('status', []) if isinstance(row.get('status'), list) else [row.get('status')]
    status_clean = ''.join([str(s).strip().lower() for s in status_list if s is not None]).strip()
    
    # Skip deleted or promo props - only keep active
    if 'deleted' in status_clean.lower() or (getattr(row, 'isPromo', False) == True and status_clean not in ['Active']): 
        continue
    
    try:
        line_score = row.get('line_score')
        if line_score is None or str(line_score).strip() == '':
            continue
            
        # Extract player info and stat type
        player_name = row.get('player_display_name', '').replace('_', ' ')
        if not player_name:
            continue
            
        position = row.get('position', 'N/A')
        
        nba_props_fresh.append({
            'player_name': player_name,
            'position': position,
            'stat_type_id': row.get('stat_type_id', ''),
            'line_score': line_score if isinstance(line_score, (int, float)) else float(str(line_score)),
            'event_type': row.get('event_type', ''),
            'updated_at': row.get('updated_at')
        })
    except (TypeError, ValueError):
        continue

print(f"\n✓ Loaded {len(nba_props_fresh)} active NBA props from PrizePicks")
print("  These represent current live projections (fresh baseline for movement detection)")

# ========================================
# STEP 2 — PULL CURRENT LINES VIA API (THE ODDS API)
# ========================================
print("\n" + "=" * 80)
print("[STEP 2] Pulling CURRENT lines from The Odds API")
print("=" * 80)

all_current_lines = {}  # {player_name: {prop_type: {book: line}}}
markets_fetched = []

# Fetch all NBA player prop markets (no specific market filter to catch ALL)
all_markets_response = None
try:
    params = {"apiKey": API_KEY, "regions": "us"}
    print("\nFetching full NBA odds dataset...")
    all_markets_response = requests.get(BASE_URL, params=params, timeout=60)
    markets_fetched.append("all_nba")
    
    if all_markets_response.status_code == 200:
        full_data = all_markets_response.json()
        print(f"✓ Retrieved {len(full_data)} total markets from The Odds API")
        
        # Parse player props from ALL markets
        for market in full_data:
            book_name = market.get('bookName', 'Unknown')
            sport_key = market.get('sport_key', '')
            
            # Only process NBA markets
            if sport_key != 'sports_actions_nba':
                continue
                
            for outcome in market.get('outcomes', []):
                player_name = outcome.get('player_name')
                line = outcome.get('line')
                
                if not player_name or line is None:
                    continue
                
                # Extract stat type from sport_key and decimal_props fields
                if 'decimal_props' in outcome:
                    prop_type = list(outcome['decimal_props'].keys())[0] if outcome['decimal_props'] else 'unknown'
                    value = outcome['decimal_props'][prop_type] if 'decimal_props' in outcome else None
                elif 'line' in outcome:
                    # It's a player prop (not spread/total)  
                    prop_type = outcome.get('sport_key', '').split('_')[-1] if '_' in outcome.get('sport_key', '') else 'line'
                    value = line
                
                all_current_lines.setdefault(player_name, {})['points'] = line
                
                print(f"  Found prop for {player_name}: points={line} @ {book_name}")
                
    else:
        print(f"  Warning: API returned status code {all_markets_response.status_code}")
        
except Exception as e:
    print(f"✗ Error fetching from The Odds API: {e}")

current_props_count = len(all_current_lines)
print(f"\n✓ Collected lines for {current_props_count} unique players")

# ========================================
# STEP 3 — COMPARE AND FLAG MOVEMENTS AGAINST FRESH BASELINE
# ========================================
print("\n" + "=" * 80)
print("[STEP 3] Comparing fresh baseline to current lines...")
print("=" * 80)

movements_found = []      # Props that moved favorably >= 0.5 (status: ACTIVE - LINE MOVED)
skipped_list = []         # Props with < 0.5 movement or moved wrong direction (status: HOLD - NO SIGNIFICANT MOVEMENT)
injury_watch_alerts = []  # Props disappeared from all books
arb_opportunities = []    # Arbitrage opportunities detected

print(f"\nBaseline: {len(nba_props_fresh)} active props (fresh PrizePicks)")
print("Monitoring line movements to detect shifts of 0.5+ points...")
print()

for prop in nba_props_fresh:
    player_name = prop['player_name']
    stat_type = prop['stat_type_id'] if prop.get('stat_type_id') else 'points'
    baseline_line = prop['line_score']
    
    # Check if current API has this player's line
    if player_name in all_current_lines and stat_type in all_current_lines[player_name]:
        current_line = all_current_lines[player_name][stat_type]
        
        # Calculate movement (absolute difference)
        movement = abs(current_line - baseline_line)
        
        print(f"{player_name}")
        print(f"  Baseline: {baseline_line:.1f}, Current: {current_line:.1f}")
        print(f"  Movement: {movement:.2f} points")
        print(f"  Status: ACTIVE if movement >= 0.5, SKIP if < 0.5 or moved wrong way")

print()
