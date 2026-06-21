#!/usr/bin/env python3
"""One-time installer: wire the committed hooks/pre-push hook into this git repo.

Sets git config core.hooksPath to 'hooks' (the committed hooks directory at
the repo root) and ensures the pre-push hook has the executable bit. This
makes every subsequent `git push` trigger the fast CI gate automatically
without any manual step (CI-01).

SAFE to re-run: core.hooksPath is idempotent (git config is a simple
key=value write). The chmod is also idempotent.

Install (one-time, after a fresh clone or to verify the hook is active):
    cd scripts
    python3 install_hooks.py

Verify it took:
    git config --get core.hooksPath   # should print: hooks
    test -x ../hooks/pre-push && echo "executable: OK"

To re-install (e.g. after git config was reset):
    cd scripts && python3 install_hooks.py

Bypass the hook for a single push without uninstalling:
    git push --no-verify
    (Documented escape hatch — accepted on the operator's own machine. The
    hook is a safety net, not a security control; bypassing it is at the
    operator's discretion. The gate can always be run manually with
    `cd scripts && python3 run_ci_gate.py`.)

Background (D-01/CI-01):
    .git/hooks/ is NOT version-controlled, so placing the hook there would
    lose it after a fresh clone. Instead, we store the hook at hooks/pre-push
    (committed, version-controlled) and point git at it via core.hooksPath.
    This is the standard 'committed hooks directory' pattern supported since
    git 2.9.

    core.hooksPath is verified UNSET on this repo before first install
    (default is .git/hooks/). Setting it to 'hooks' is non-destructive.
    If it is already set to something else, this installer reports the
    current value and sets it to 'hooks' (overwrite is intentional for
    re-install scenarios).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — derived portably, no hardcoded absolute paths.
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = SCRIPTS_DIR.parent
HOOKS_DIR: Path = REPO_ROOT / "hooks"
HOOK_FILE: Path = HOOKS_DIR / "pre-push"

HOOKS_PATH_KEY = "core.hooksPath"
HOOKS_PATH_VALUE = "hooks"


def main() -> int:
    """Install the committed pre-push hook into this git repo. Returns 0 on success."""
    print(f"[install_hooks] REPO_ROOT: {REPO_ROOT}")
    print(f"[install_hooks] HOOKS_DIR: {HOOKS_DIR}")

    # Verify the committed hook exists before installing.
    if not HOOK_FILE.exists():
        print(
            f"[install_hooks] ERROR: hook file not found at {HOOK_FILE}.\n"
            "Ensure 'hooks/pre-push' is committed in the repository.",
            file=sys.stderr,
        )
        return 1

    # Check current core.hooksPath value (informational; we always set it).
    try:
        result = subprocess.run(
            ["git", "config", "--get", HOOKS_PATH_KEY],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        current_value = result.stdout.strip()
        if current_value:
            print(
                f"[install_hooks] {HOOKS_PATH_KEY} is currently set to: {current_value!r} "
                f"(will overwrite with {HOOKS_PATH_VALUE!r})"
            )
        else:
            print(
                f"[install_hooks] {HOOKS_PATH_KEY} is currently UNSET (default .git/hooks/). "
                f"Setting to {HOOKS_PATH_VALUE!r} — non-destructive."
            )
    except Exception as exc:
        print(f"[install_hooks] Warning: could not read {HOOKS_PATH_KEY}: {exc}", file=sys.stderr)

    # Set core.hooksPath = hooks (points git at our committed hooks directory).
    try:
        subprocess.run(
            ["git", "config", HOOKS_PATH_KEY, HOOKS_PATH_VALUE],
            cwd=str(REPO_ROOT),
            check=True,
        )
        print(f"[install_hooks] Set {HOOKS_PATH_KEY}={HOOKS_PATH_VALUE!r} — OK")
    except subprocess.CalledProcessError as exc:
        print(
            f"[install_hooks] ERROR: failed to set {HOOKS_PATH_KEY}: {exc}",
            file=sys.stderr,
        )
        return 1

    # Ensure the hook has the executable bit (chmod +x).
    try:
        os.chmod(HOOK_FILE, 0o755)
        print(f"[install_hooks] chmod 0o755 on {HOOK_FILE} — OK")
    except OSError as exc:
        print(
            f"[install_hooks] ERROR: could not chmod {HOOK_FILE}: {exc}",
            file=sys.stderr,
        )
        return 1

    # Verify: read back core.hooksPath and check executable bit.
    result = subprocess.run(
        ["git", "config", "--get", HOOKS_PATH_KEY],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    verified_value = result.stdout.strip()
    if verified_value != HOOKS_PATH_VALUE:
        print(
            f"[install_hooks] ERROR: verification failed — "
            f"{HOOKS_PATH_KEY} is {verified_value!r}, expected {HOOKS_PATH_VALUE!r}.",
            file=sys.stderr,
        )
        return 1

    hook_executable = os.access(HOOK_FILE, os.X_OK)
    if not hook_executable:
        print(
            f"[install_hooks] ERROR: {HOOK_FILE} is not executable after chmod.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\n[install_hooks] SUCCESS\n"
        f"  {HOOKS_PATH_KEY} = {verified_value!r}\n"
        f"  {HOOK_FILE} is executable: {hook_executable}\n"
        f"\n"
        f"Every 'git push' will now trigger the CI gate automatically.\n"
        f"To bypass a single push: git push --no-verify\n"
        f"To run the gate manually: cd scripts && python3 run_ci_gate.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
