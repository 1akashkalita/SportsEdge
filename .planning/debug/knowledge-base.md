# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## dnp-missing-stat — NBA combo stats defaulted missing keys to 0 while single stats abstained
- **Date:** 2026-06-22
- **Error patterns:** MANUAL REVIEW, stat_value_for_prop, DNP, missing stat, inconsistent, combo, PRA, pts+rebs+asts, or 0
- **Root cause:** PRA/combo stats used `or 0.0` fallbacks for absent keys, grading a missing component as 0 (LOSS); single-stat `_direct` used `or` chaining that treated genuine 0 as falsy (None → MANUAL REVIEW). Same player row, inconsistent outcomes.
- **Fix:** Added `_flat_get(*keys)` sentinel helper using `object()` to distinguish key-absent from key-present-but-zero. Combos guard each component `if X is None: return _MANUAL`; direct lookups use `_flat_get`.
- **Files changed:** scripts/sports_system_runner.py, scripts/test_stat_value_for_prop.py
---
