#!/usr/bin/env python3
"""Send today's SportsEdge slip recommendations to Telegram after audit passes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

PT = ZoneInfo("America/Los_Angeles")
HOME = Path.home()
ROOT = HOME / "sports_picks"
SLIPS_DIR = ROOT / "data" / "research" / "slips"
HERMES_ENV = HOME / ".hermes" / ".env"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "hermes_sports_cron.log"
ERR_FILE = LOG_DIR / "hermes_sports_cron_errors.log"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TELEGRAM_LEN = 3900


def today_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d")


def resolve_date(value: str | None) -> str:
    if not value or value.lower() == "today":
        return today_pt()
    return value


def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    if not HERMES_ENV.exists():
        return None
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'") or None
    return None


def log(message: str, error: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = ERR_FILE if error else LOG_FILE
    stamp = datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S %Z")
    with target.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")


def chunk_text(text: str, limit: int = MAX_TELEGRAM_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return chunks


def send_telegram(message: str) -> int:
    token = env_value("TELEGRAM_BOT_TOKEN")
    chat_id = env_value("TELEGRAM_HOME_CHANNEL") or env_value("TELEGRAM_CHAT_ID")
    thread_id = env_value("TELEGRAM_CRON_THREAD_ID") or env_value("TELEGRAM_HOME_CHANNEL_THREAD_ID")
    if not token or not chat_id:
        log("Slip Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL missing", error=True)
        return 2
    url = TELEGRAM_API.format(token=token)
    for idx, chunk in enumerate(chunk_text(message), start=1):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if thread_id:
            payload["message_thread_id"] = thread_id
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code != 200:
                log(f"Slip Telegram notification failed on chunk {idx}: status={resp.status_code} body={resp.text[:300]}", error=True)
                return 1
        except Exception as exc:
            log(f"Slip Telegram notification failed on chunk {idx}: {exc}", error=True)
            return 1
    log(f"Slip Telegram notification sent: chunks={len(chunk_text(message))}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    date = resolve_date(args.date)
    md_path = SLIPS_DIR / f"slips_{date}.md"
    json_path = SLIPS_DIR / f"slips_{date}.json"
    if md_path.exists():
        body = md_path.read_text(encoding="utf-8", errors="ignore").strip()
    elif json_path.exists():
        body = json.dumps(json.loads(json_path.read_text(encoding="utf-8")), indent=2)
    else:
        log(f"Slip Telegram notification failed: no slip output found for {date} at {md_path} or {json_path}", error=True)
        return 1
    if not body:
        log(f"Slip Telegram notification skipped: slip output empty for {date}", error=True)
        return 1
    message = f"🎟️ SportsEdge Slip Recommendations — {date}\n\n{body}"
    return send_telegram(message)


if __name__ == "__main__":
    raise SystemExit(main())
