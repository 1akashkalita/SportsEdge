---
phase: quick-260621-ohh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: [scripts/send_slips_telegram.py]
autonomous: true
requirements: [QUICK-260621-ohh]
must_haves:
  truths:
    - "send_slips_telegram.py performs its Telegram HTTPS POST via the requests library (certifi CA bundle), not urllib"
    - "The script no longer references urllib anywhere (no remaining CERTIFICATE_VERIFY_FAILED surface)"
    - "send_telegram preserves its return-code contract: 0 success, 1 failure, 2 missing creds, and same chunking"
    - "Running the script with a date that has no slip output exits cleanly (no traceback) without contacting Telegram"
  artifacts:
    - path: "scripts/send_slips_telegram.py"
      provides: "Telegram slip notifier using requests for HTTP"
      contains: "import requests"
  key_links:
    - from: "scripts/send_slips_telegram.py:send_telegram"
      to: "requests.post"
      via: "HTTP POST to TELEGRAM_API"
      pattern: "requests\\.post\\("
---

<objective>
Fix the slip-notification cron SSL failure. `scripts/send_slips_telegram.py` posts to the
Telegram API via `urllib.request.urlopen`, whose default SSL context on the operator's
python.org macOS build lacks a CA bundle → `CERTIFICATE_VERIFY_FAILED`. Every other HTTP
caller in the repo uses `requests` (which ships certifi's CA bundle and does not fail).

Purpose: Make the slip-notification cron job send reliably, matching the established
`requests`-based pattern already used by `sports_system_runner.py:send_telegram`.
Output: `scripts/send_slips_telegram.py` migrated from `urllib` to `requests`, with the
exact same behavior, return codes, log strings, and chunking.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Reference pattern already proven in this repo. Mirror its HTTP mechanism + checks. -->

From scripts/sports_system_runner.py:421 (send_telegram, the established pattern):
```python
r = requests.post(TELEGRAM_API.format(token=token), json=payload, timeout=10)
if r.status_code == 200:
    ...
log(f"... status={r.status_code} body={r.text[:300]}")
```
`requests` 2.34.2 is already installed in `/usr/local/bin/python3` (no new dependency).

Current send_slips_telegram.py surface to change:
- Lines 9-10: `import urllib.parse` (UNUSED — confirmed only at the import line) and
  `import urllib.request`. Both are replaced by `import requests`.
- Lines 94-104 inside the per-chunk loop in `send_telegram`: build `data` bytes, a
  `urllib.request.Request`, then `urllib.request.urlopen(req, timeout=20)`, checking
  `resp.status != 200` and reading `resp.read()`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migrate send_slips_telegram.py from urllib to requests</name>
  <files>scripts/send_slips_telegram.py</files>
  <action>
    Replace the HTTP mechanism only — behavior, return codes, log strings, and chunking
    must stay identical.

    1. Imports: delete `import urllib.parse` (line 9, unused) and `import urllib.request`
       (line 10). Add `import requests` in their place, preserving alphabetical/stdlib
       grouping conventions (place `import requests` after the stdlib imports — it is the
       only third-party import).

    2. Inside `send_telegram`, in the per-chunk `for` loop (currently lines 86-104), replace
       the urllib block:
       - Remove the `data = json.dumps(payload).encode("utf-8")` line and the
         `req = urllib.request.Request(...)` line.
       - Replace the `try: with urllib.request.urlopen(req, timeout=20) as resp: ...` block
         with: `resp = requests.post(url, json=payload, timeout=20)` inside the `try`, then
         check `if resp.status_code != 200:` and log
         `f"Slip Telegram notification failed on chunk {idx}: status={resp.status_code} body={resp.text[:300]}"`
         (error=True) and `return 1`. (`requests` serializes `payload` and sets the JSON
         Content-Type automatically via the `json=` kwarg, so drop the manual encode/header.)
       - Keep the existing broad `except Exception as exc:` that logs
         `f"Slip Telegram notification failed on chunk {idx}: {exc}"` and returns 1.
       - Keep the `idx`/`chunk` loop, the `if thread_id: payload["message_thread_id"] = thread_id`
         line, the final success `log(...)` + `return 0`, and the missing-creds `return 2`
         path entirely unchanged.

    Do NOT change `chunk_text`, `main`, `env_value`, `log`, return codes, or any log message
    wording other than `resp.status` → `resp.status_code` already shown above. No new
    dependencies (requests is already installed). Per CLAUDE.md: minimal-invasive,
    HTTP-mechanism-only change.
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import ast; ast.parse(open('send_slips_telegram.py').read()); print('SYNTAX_OK')" && grep -q '^import requests' send_slips_telegram.py && echo IMPORT_OK && grep -q 'requests\.post(' send_slips_telegram.py && echo POST_OK && test "$(grep -c 'urllib' send_slips_telegram.py)" -eq 0 && echo NO_URLLIB_OK</automated>
  </verify>
  <done>
    File parses; `import requests` present; `requests.post(` present; zero remaining
    `urllib` references anywhere in the file; chunking loop, return codes (0/1/2), and log
    strings unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 2: Smoke-verify the script runs without raising and never hits Telegram</name>
  <files>scripts/send_slips_telegram.py</files>
  <action>
    No code change. Confirm the migrated script imports cleanly and that the no-slip-output
    code path (which short-circuits in `main` before reaching `send_telegram`) exits
    cleanly. This avoids contacting Telegram entirely — there are no creds in the test
    context and no slip file for the sentinel date, so `main` returns 1 via the
    "no slip output found" branch without raising.

    If the import-only check is desired separately, `python3 -c "import send_slips_telegram"`
    (run from `scripts/`) must succeed, proving `requests` resolves and there is no leftover
    `urllib` import error.
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import send_slips_telegram; print('IMPORT_OK')" && python3 send_slips_telegram.py --date 1999-01-01; rc=$?; test "$rc" -eq 1 && echo "CLEAN_EXIT_OK rc=$rc"</automated>
  </verify>
  <done>
    `import send_slips_telegram` succeeds (requests resolves, no urllib import error);
    `python3 send_slips_telegram.py --date 1999-01-01` exits with code 1 via the
    "no slip output found" path, producing no traceback and making no Telegram request.
  </done>
</task>

</tasks>

<verification>
- `python3 -c "import ast; ast.parse(...)"` parses the file (no syntax error).
- `grep` confirms `import requests` present, `requests.post(` present, and zero `urllib`
  occurrences.
- `import send_slips_telegram` succeeds from `scripts/`.
- `python3 send_slips_telegram.py --date 1999-01-01` exits cleanly (rc=1, no traceback),
  never reaching the Telegram POST.
- No new dependency added (requests already installed at version 2.34.2).
</verification>

<success_criteria>
- The Telegram HTTPS POST in `send_telegram` uses `requests.post(..., json=payload, timeout=20)`.
- Return-code contract preserved exactly: 0 = success, 1 = send/no-output failure, 2 = missing creds.
- Chunking (`chunk_text`), thread-id handling, and all log message strings unchanged.
- No `urllib` references remain anywhere in the file.
- Static + import + clean-exit checks all pass without hitting Telegram's API.
</success_criteria>

<output>
Create `.planning/quick/260621-ohh-fix-send-slips-telegram-urllib-requests-/260621-ohh-SUMMARY.md` when done
</output>
