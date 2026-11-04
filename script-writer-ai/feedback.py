"""Saving reviews to a CSV file and forwarding them to a Discord channel."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import requests

FEEDBACK_COLUMNS = [
    "time", "copy_type", "platform", "product", "audience", "qualities", "offer",
    "language", "length", "tone", "version_note", "script", "rating", "whats_weak",
    "expert_rewrite",
]


def save_feedback(row: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f), [])
        if header != FEEDBACK_COLUMNS:  # older file format: keep it, start a fresh file
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            path.rename(path.with_name(f"{path.stem}_old_{stamp}{path.suffix}"))
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FEEDBACK_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in FEEDBACK_COLUMNS})


def feedback_csv_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def notify_developer(row: dict, webhook_url: str) -> bool:
    """Send a saved review to Discord. Never raises, so saving can't break."""
    if not webhook_url:
        return False
    text = (
        f"📝 New review: {row.get('rating')}/5 · {row.get('copy_type')}\n"
        f"{row.get('product')} | {row.get('platform')} | {row.get('language')} | "
        f"{row.get('length')} | {row.get('tone')}{(' | ' + row['version_note']) if row.get('version_note') else ''}\n\n"
        f"COPY:\n{row.get('script')}\n\n"
        f"WEAK: {row.get('whats_weak') or '-'}\n\n"
        f"HER REWRITE: {row.get('expert_rewrite') or '-'}"
    ).replace("@", "@\u200b")  # stops @everyone pings from user text
    try:
        if len(text) <= 1900:
            r = requests.post(webhook_url, json={"content": text}, timeout=15)
        else:  # Discord limit is 2000 chars, so attach the full text as a file
            r = requests.post(webhook_url, data={"content": text[:1900] + "…"},
                              files={"file": ("review.txt", text.encode("utf-8"))}, timeout=15)
        return r.status_code < 300
    except requests.RequestException:
        return False
