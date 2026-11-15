"""Saving reviews to a CSV file and sending everything the tool does to a Discord channel."""
from __future__ import annotations

import csv
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

from prompt import Brief, get_copy_type, resolve_format

FEEDBACK_COLUMNS = [
    "time", "copy_type", "format", "platform", "product", "audience", "qualities", "offer",
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
        f"{row.get('product')} | {row.get('format') or '-'} | {row.get('platform')} | {row.get('language')} | "
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


# ---------------------------------------------------------------------------
# Discord log: every generation, refine and fix, with every detail the user entered
# ---------------------------------------------------------------------------
DISCORD_LIMIT = 1900          # Discord allows 2000 characters per message


def _clean(text: str) -> str:
    """Keep user text from breaking the code block or pinging @everyone."""
    return (text or "").replace("```", "'''").replace("@", "@\u200b")


def _chunk_lines(text: str, limit: int) -> list:
    """Split on line breaks (and, for one huge line, mid-line) so every piece fits the limit."""
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def chunk_text(text: str, limit: int) -> list:
    """Split at blank lines first, so a shot-list segment is never cut in half."""
    chunks, current = [], ""
    for paragraph in text.split("\n\n"):
        if len(paragraph) > limit:                  # one paragraph too big: fall back to lines
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_chunk_lines(paragraph, limit))
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def block_messages(header: str, body: str, footer: str = "", limit: int = DISCORD_LIMIT) -> list:
    """Split a long text into Discord-sized messages, each with its own code block."""
    header, body, footer = _clean(header), _clean(body), _clean(footer)[:700]
    room = max(300, limit - len(header) - len(footer) - 40)
    parts = chunk_text(body.strip() or "-", room)
    messages = []
    for i, part in enumerate(parts):
        top = header if i == 0 else f"(part {i + 1} of {len(parts)}) {header.splitlines()[0][:70]}"
        bottom = f"\n{footer}" if footer and i == len(parts) - 1 else ""
        messages.append(f"{top}\n```\n{part}\n```{bottom}")
    return messages


def brief_lines(brief: Brief) -> list:
    """Every field the user could fill in for this copy type, empty ones shown as '-'."""
    ct = get_copy_type(brief.copy_type)

    def val(v) -> str:
        v = (v or "").strip()
        return v if v else "-"

    def items(values: list) -> list:
        return [f"  - {v}" for v in values] or ["  -"]

    lines = [f"Type: {ct.label}"]
    if ct.formats:
        lines.append(f"Format: {resolve_format(ct, brief)}")
    lines += [f"Product: {val(brief.product)}", f"Audience: {val(brief.audience)}", "Key qualities:"]
    lines += items(brief.qualities_clean)
    lines.append("Problems it solves:")
    lines += items(brief.pain_points_clean)
    lines.append(f"Offer: {val(brief.offer)}")
    if ct.supports_cta:
        lines.append(f"Call to action: {val(brief.cta)}")
    lines += [f"Language: {val(brief.language)}", f"Length: {val(brief.length)}",
              f"Tone: {val(brief.tone)}", f"Platform: {val(brief.platform)}"]
    if ct.formats:
        lines.append(f"Shots they can film: {val(brief.shots)}")
    for key, toggle in ct.toggles.items():
        lines.append(f"{toggle.label}: {'yes' if brief.toggles.get(key, toggle.default) else 'no'}")
    if ct.keywords_label:
        lines.append(f"Keywords: {val(brief.keywords)}")
    lines += [f"Words or claims to avoid: {val(brief.avoid)}", f"Extra details: {val(brief.extra)}"]
    return lines


def _checks_line(problems: list | None) -> str:
    if not problems:
        return "\u2705 Passed all automatic checks"
    return "\u26a0\ufe0f " + " | ".join(problems)


def generation_messages(sid: str, brief: Brief, versions: list, settings: str = "",
                        requests_so_far: int = 0) -> list:
    """versions: [{"text", "note", "problems"}]. First message is the full brief."""
    ct = get_copy_type(brief.copy_type)
    header = f"\U0001F195 **#{sid}** New {ct.label.lower()} \u00b7 AI request #{requests_so_far}"
    body = "\n".join(brief_lines(brief) + ([settings] if settings else []))
    messages = block_messages(header, body)
    for i, v in enumerate(versions, start=1):
        note = f" \u00b7 {v['note']}" if v.get("note") else ""
        messages += block_messages(f"**#{sid} Version {i}**{note}", v["text"],
                                   _checks_line(v.get("problems")))
    return messages


def followup_messages(sid: str, brief: Brief, item: dict, requests_so_far: int = 0) -> list:
    """A refined or fixed version created later in the same session."""
    ct = get_copy_type(brief.copy_type)
    what = item.get("note") or "New version"
    header = (f"\U0001F501 **#{sid}** {what} \u00b7 {ct.label} \u00b7 {brief.product.strip()[:60]} \u00b7 "
              f"{brief.language} \u00b7 {brief.length} \u00b7 AI request #{requests_so_far}")
    return block_messages(header, item["text"], _checks_line(item.get("problems")))


def _post_one(webhook_url: str, content: str) -> bool:
    for attempt in range(2):
        try:
            r = requests.post(webhook_url, json={"content": content}, timeout=15)
        except requests.RequestException:
            return False
        if r.status_code == 429 and attempt == 0:      # Discord asks us to slow down
            try:
                wait = float(r.json().get("retry_after", 1))
            except Exception:
                wait = 1.0
            time.sleep(min(wait, 5))
            continue
        return r.status_code < 300
    return False


def post_discord(webhook_url: str, messages: list, pause: float = 0.6) -> bool:
    """Send messages one after another. Never raises."""
    if not webhook_url:
        return False
    ok = True
    for text in messages:
        ok = _post_one(webhook_url, text) and ok
        time.sleep(pause)                              # stay under Discord's rate limit
    return ok


def post_discord_async(webhook_url: str, messages: list):
    """Send in the background so the app never waits for Discord."""
    if not webhook_url or not messages:
        return None
    thread = threading.Thread(target=post_discord, args=(webhook_url, messages), daemon=True)
    thread.start()
    return thread


def note_messages(sid: str, text: str) -> list:
    """A one-line event for the log, e.g. the user asked for another option."""
    return [_clean(f"\U0001F440 **#{sid}** {text}")]
