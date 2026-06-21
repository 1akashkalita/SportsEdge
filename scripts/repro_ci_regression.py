#!/usr/bin/env python3
"""
repro_ci_regression.py — Phase 5 CI / Criterion-3 regression proof.

PURPOSE
-------
Prove that the Wave-1 ``run_ci_gate.py`` gate actually CATCHES a deliberate regression
in a tested code path, not just that it runs green.  ROADMAP success criterion 3:

  "A deliberate regression to a tested code path causes the CI run to fail and surface it."

MECHANISM (fault-injection-by-construction — mirrors Phase-3 RES-04 rigor)
---------------------------------------------------------------------------
Target: ``slip_payouts.py`` → ``_clean_slip_type()`` function.
Test coverage: ``test_slip_payouts.py`` exercises every payout calculation via
``calculate_slip_payout(..., slip_type="power")`` and ``slip_type="flex"``; these
go through ``_clean_slip_type()`` on every call.  The function is included in the
denylist subset (``test_slip_payouts.py`` is NOT in the DENYLIST exclusion list), so
any fault here will be surfaced by the gate.

Fault injected: replace the ``return "power"`` line with
  ``return "FAULT_INJECTED"  # DELIBERATE TEST FAULT``
This makes every "power" slip-type lookup fail (returns None instead of a multiplier),
breaking all power-slip payout assertions in ``test_slip_payouts.py``.

FAILS-WITHOUT / PASSES-WITH (RES-04 by-construction guarantee)
---------------------------------------------------------------
FAILS WITHOUT this harness: a regression in ``_clean_slip_type`` would silently
  ship — the gate would pass green while payouts were broken.

PASSES WITH this harness (the correct behavior):
  STEP 1 — inject fault → run gate → assert NON-ZERO (RED: gate surfaced regression).
  STEP 2 — revert fault → run gate → assert ZERO (GREEN: gate restored clean).
  The harness can only exit 0 (PASS) if BOTH assertions hold — it cannot pass by
  accident because:
    - STEP 1 exiting 0 from the gate would map to exit code 2 (REGRESSION NOT CAUGHT)
    - STEP 2 exiting non-zero from the gate would map to exit code 1 (INFRA FAIL)

REVERT GUARANTEE (T-05-07 / T-05-08 mitigations)
-------------------------------------------------
The original source bytes are saved before mutation and restored unconditionally in a
``finally`` block.  Even an exception or KeyboardInterrupt during the gate run triggers
the finally revert.  After the harness exits, the source file is byte-identical to
before (verified by the acceptance criterion: ``git diff`` shows no residual change).

TIMING NOTE (observed on this machine, 2026-06-21)
---------------------------------------------------
- Clean subset run (no fault): ~28 min (1705s)
- Faulted subset run (6 failures + failure report): ~32 min (1925s)
- ``_GATE_TIMEOUT = 3600.0`` (60 min) gives 28 min headroom above observed failure timing.

EXIT CODES
----------
  0 — PASS: gate went RED on the injected fault (non-zero), then GREEN after revert (0).
            Criterion 3 satisfied — the gate catches real regressions.
  1 — INFRA FAIL: could not inject/revert the fault, or could not run the gate.
                  The proof could not run cleanly; investigate before trusting the gate.
  2 — REGRESSION NOT CAUGHT: gate stayed GREEN despite the injected fault.
                              The gate is NOT reliable — a regression slipped through.

Run from scripts/:
    python3 repro_ci_regression.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — derived portably, NO hardcoded absolute paths.
# (test_def02_path_resolution.py does NOT scan this file; the no-hardcoded-path
#  property is enforced by the per-file acceptance criterion in 05-03-PLAN.md.)
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent

# The target source file whose ``_clean_slip_type`` we temporarily mutate.
TARGET_FILE: Path = SCRIPTS_DIR / "slip_payouts.py"

# The line that identifies the injection site (exact text match in the source).
ORIGINAL_LINE: str = '        return "power"\n'

# The replacement that introduces the deliberate fault.
FAULT_LINE: str = '        return "FAULT_INJECTED"  # DELIBERATE TEST FAULT\n'

# How long (seconds) to wait for each gate run.
# Observed timings on this machine:
#   - clean subset (no fault): ~28 min (1705s)
#   - faulted subset (6 failures): ~32 min (1925s) — failure reporting adds ~3.7 min
# We give 60 min to cover machine variance on both passes.
# The revert-guaranteed finally block runs independent of this timeout.
_GATE_TIMEOUT: float = 3600.0


def _run_gate(label: str) -> int:
    """Spawn run_ci_gate.py in a subprocess; return its exit code.

    Uses sys.executable so the same python3 that runs this harness runs the gate —
    matching the CI-02 / production interpreter contract.

    Returns the gate's exit code, or -1 on spawn/timeout failure (logged to stderr).
    """
    print(f"\n[repro_ci] running gate ({label}) ...")
    try:
        result = subprocess.run(
            [sys.executable, "run_ci_gate.py"],
            cwd=str(SCRIPTS_DIR),
            timeout=_GATE_TIMEOUT,
        )
        code = result.returncode
        print(f"[repro_ci] gate exit code ({label}): {code}")
        return code
    except subprocess.TimeoutExpired:
        print(
            f"[repro_ci] INFRA FAIL: gate timed out after {_GATE_TIMEOUT:.0f}s ({label})",
            file=sys.stderr,
        )
        return -1
    except Exception as exc:
        print(
            f"[repro_ci] INFRA FAIL: could not spawn gate ({label}): {exc}",
            file=sys.stderr,
        )
        return -1


def main() -> int:
    """Inject fault → RED → revert → GREEN.  Return tri-state exit code."""

    # ------------------------------------------------------------------
    # 1.  Read and validate the original source before touching anything.
    # ------------------------------------------------------------------
    try:
        original_bytes: bytes = TARGET_FILE.read_bytes()
    except Exception as exc:
        print(
            f"INFRA FAIL: cannot read target file {TARGET_FILE}: {exc}",
            file=sys.stderr,
        )
        return 1

    original_text: str = original_bytes.decode("utf-8", errors="replace")

    if ORIGINAL_LINE not in original_text:
        print(
            f"INFRA FAIL: injection target line not found in {TARGET_FILE}.\n"
            f"  Expected: {ORIGINAL_LINE!r}\n"
            "  The source may have been refactored.  Update ORIGINAL_LINE to match.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[repro_ci] target:         {TARGET_FILE}\n"
        f"[repro_ci] original line:  {ORIGINAL_LINE.rstrip()!r}\n"
        f"[repro_ci] fault line:     {FAULT_LINE.rstrip()!r}\n"
        f"[repro_ci] gate timeout:   {_GATE_TIMEOUT:.0f}s per run"
    )

    # ------------------------------------------------------------------
    # 2.  Inject the fault, run the gate (expect RED), then GUARANTEE REVERT.
    # ------------------------------------------------------------------
    gate_red_code: int = -1
    gate_green_code: int = -1
    revert_ok: bool = False

    faulted_text = original_text.replace(ORIGINAL_LINE, FAULT_LINE, 1)

    try:
        # --- inject ---
        print("\n[repro_ci] STEP 1: injecting fault ...")
        TARGET_FILE.write_bytes(faulted_text.encode("utf-8"))
        print(f"[repro_ci] fault injected: {FAULT_LINE.rstrip()!r}")

        # --- gate run #1 (should be RED) ---
        gate_red_code = _run_gate("after-injection / expect RED")

    finally:
        # --- UNCONDITIONAL REVERT (T-05-07 / T-05-08 mitigations) ---
        print("\n[repro_ci] STEP 2: reverting fault (unconditional finally) ...")
        try:
            TARGET_FILE.write_bytes(original_bytes)
            # Verify the restore by re-reading and comparing.
            restored_bytes = TARGET_FILE.read_bytes()
            if restored_bytes == original_bytes:
                revert_ok = True
                print("[repro_ci] revert confirmed: source is byte-identical to original.")
            else:
                print(
                    "INFRA FAIL: revert wrote bytes but they do NOT match the original!",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(
                f"INFRA FAIL: could not revert {TARGET_FILE}: {exc}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # 3.  Run the gate AFTER revert (expect GREEN).  Only if revert succeeded.
    # ------------------------------------------------------------------
    if not revert_ok:
        print(
            "\nINFRA FAIL: revert failed — cannot run post-revert gate check.\n"
            "The source file MAY be mutated.  Run 'git diff scripts/slip_payouts.py' to verify.",
            file=sys.stderr,
        )
        return 1

    gate_green_code = _run_gate("after-revert / expect GREEN")

    # ------------------------------------------------------------------
    # 4.  Evaluate tri-state outcome.
    # ------------------------------------------------------------------
    print("\n[repro_ci] --- CRITERION-3 VERDICT ---")
    print(f"[repro_ci] gate after injection (expect NON-ZERO / RED): {gate_red_code}")
    print(f"[repro_ci] gate after revert    (expect ZERO   / GREEN): {gate_green_code}")

    # Infra failure paths
    if gate_red_code == -1:
        print(
            "\nINFRA FAIL (exit 1): gate could not run after fault injection.\n"
            "Fix the infra issue before re-running the proof."
        )
        return 1

    if gate_green_code == -1:
        print(
            "\nINFRA FAIL (exit 1): gate could not run after fault revert.\n"
            "Fix the infra issue before re-running the proof."
        )
        return 1

    # Regression-not-caught: gate stayed green despite the fault
    if gate_red_code == 0:
        print(
            "\nREGRESSION NOT CAUGHT (exit 2): gate returned 0 (GREEN) even with the fault "
            "injected.\nThe gate is NOT catching this regression.  Criterion 3 NOT satisfied."
        )
        return 2

    # Green-after-revert check
    if gate_green_code != 0:
        print(
            f"\nINFRA FAIL (exit 1): gate returned {gate_green_code} (not 0) after revert.\n"
            "Pre-existing test failures or an incomplete revert may be the cause.\n"
            "Run 'python3 run_ci_gate.py' and 'git diff scripts/slip_payouts.py' to investigate."
        )
        return 1

    # PASS: gate went RED then GREEN as expected
    print(
        f"\nPASS (exit 0): criterion 3 satisfied.\n"
        f"  gate RED on fault  (non-zero exit {gate_red_code})  -- regression surfaced.\n"
        f"  gate GREEN on revert (exit 0)                        -- regression resolved.\n"
        f"  source file byte-identical to original (revert confirmed).\n"
        f"The gate catches a deliberate regression in a tested code path and restores clean."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
