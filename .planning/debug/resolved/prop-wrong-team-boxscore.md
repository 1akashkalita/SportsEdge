---
status: resolved
trigger: "when i look at the telegram and game results it has many errors and cannot find the players box score. this is happening because it is looking at the wrong team for players. fix this"
created: 2026-06-23
updated: 2026-06-23
root_cause: "game_matches_row binds UUID-team props to the wrong same-night game via the 5-minute start-time-window/text fallbacks; player absent from that box -> 'No final stat line found' MANUAL REVIEW."
fix: "grade_game_in_workbook prop loop now binds via prop_belongs_to_game (Game ID / recognised team / strict box-score membership) instead of game_matches_row's loose fallbacks."
files_changed: "scripts/sports_system_runner.py, scripts/test_prop_wrong_team_binding.py"
verification: "RED->GREEN reproduction + 9 contract tests + 345 grading-path tests pass; verified on real mlb_2026-06-23 PCA row (no longer binds to Brewers@Reds)."
---

# Debug: prop graded against the wrong team's game ("not found in ESPN box score")

## Symptoms
- Telegram "game results" recaps show repeated `⚠️ MANUAL REVIEW: {player} {stat} not found in ESPN box score for {game}` alerts.
- Players are being looked up against the wrong team/game, so the box score doesn't contain them.

## Current Focus
- hypothesis: Player props with an Underdog UUID `Team` cannot be bound to their game by `team_aliases`, so `game_matches_row` falls through to the 5-minute start-time window (and loose text) fallback and binds the prop to the WRONG same-night game. The player is absent from that game's box score → "No final stat line found" → MANUAL REVIEW.
- next_action: add strict prop→game binding in `grade_game_in_workbook`; verify with a reproduction test.

## Evidence
- Props sheet schema (`PROPS_HEADERS`, runner:284) has a `Team` column but NO `Game ID`/`Home Team`/`Away Team` columns.
- For Underdog-only props, `Team` is an Underdog API UUID (e.g. `2ac58cf3-...`); `fetch_underdog.py:256` sets `team = appearance.get("team_id")`. `team_aliases` cannot expand a UUID (runner:5240 comment: UUIDs "never match").
- `game_matches_row` (runner:5218) for such a prop falls through to: (a) start-time window ≤300s (runner:5247-5263) and (b) text-substring fallback (runner:5264-5265). Start time does NOT uniquely identify a game → mis-bind to first same-slot game.
- PROOF (Results sheets): `Pete Crow-Armstrong` (Chicago Cub) graded against game `Milwaukee Brewers @ Cincinnati Reds` — neither team is his — note "No final stat line found for Pete Crow-Armstrong Hits" (mlb_2026-06-23.xlsx).
- Unified prop JSON DOES carry a reliable `game_id` (ESPN event id) + clean `team`, but neither is persisted into the Props sheet nor used at grade time.

## Eliminated
- NOT a box-score parser bug: `espn_player_stats_by_event` (runner:7143) correctly returns BOTH teams' players for a given event.
- NOT (entirely) a name-match bug: `De'Aaron Fox FG Attempted` MANUAL REVIEW is a *stat-parsing* gap (Fox WAS bound to his own SAS game) — a separate, smaller issue, out of scope for this fix.

## Related (not the reported symptom)
- Slip grading (`grade_slips.py build_date_box_scores`) merges ALL of the day's games into one name-keyed dict; `grade_leg` looks up by name only and never uses the leg's `team`. Same-surname collisions across games can resolve to the wrong player. Latent; does not emit the "not found" Telegram alert. Flagged for a follow-up.

## Fix
- Add strict prop→game binding used by the PROP loop in `grade_game_in_workbook`: bind iff (1) Game ID matches, OR (2) a recognized (non-UUID) `Team` matches this game's home/away, OR (3) the player appears in THIS game's box score by exact/unique-canonical match. Drop the start-time/text fallbacks for props. Spread/total/parlay binding unchanged.
