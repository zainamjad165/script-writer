"""Builds the prompt for the script writer from the buyer's brief."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).parent
RULES_FILE = BASE_DIR / "rules.md"
EXAMPLES_DIR = BASE_DIR / "examples"

VERSION_SEPARATOR = "===VERSION==="

# label -> (min words, max words) for spoken voiceover
LENGTHS = {
    "15 seconds": (35, 45),
    "30 seconds": (70, 85),
    "60 seconds": (140, 170),
}

LANGUAGES = {
    "English": "Write in simple, natural spoken English.",
    "Roman Urdu": (
        "Write in Roman Urdu: Urdu written with English letters, the way people in "
        "Pakistan speak and text. Natural and conversational, not a stiff translation. "
        "Common English words (order, delivery, link) are fine."
    ),
    "Urdu (اردو)": (
        "Write in Urdu using Urdu script. Natural spoken Urdu, not a stiff translation. "
        "Common English words (order, delivery) may stay in English."
    ),
}

TONES = ["Friendly", "Professional", "Funny", "Luxury / premium", "Urgent / exciting", "Emotional"]
PLATFORMS = ["Instagram Reels", "TikTok", "YouTube Shorts", "Facebook ad", "General video"]


@dataclass
class Brief:
    product: str
    audience: str
    qualities: list[str]
    offer: str = ""
    language: str = "English"
    length: str = "30 seconds"
    tone: str = "Friendly"
    platform: str = "General video"
    avoid: str = ""
    extra: str = ""
    versions: int = 3
    qualities_clean: list[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.qualities_clean = [q.strip() for q in self.qualities if q.strip()]

    def missing(self) -> list[str]:
        out = []
        if not self.product.strip():
            out.append("product")
        if not self.audience.strip():
            out.append("audience")
        if not self.qualities_clean:
            out.append("qualities")
        return out


def load_rules(path: Path = RULES_FILE) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def load_examples(directory: Path = EXAMPLES_DIR) -> list[dict]:
    """Load every *.json file in examples/. Each file holds a list of
    {language, length, brief{product,audience,qualities,offer}, script}.
    Bad files are skipped so one typo never breaks the app."""
    examples: list[dict] = []
    if not directory.exists():
        return examples
    for file in sorted(directory.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            data = [data]
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and item.get("script") and isinstance(item.get("brief"), dict):
                examples.append(item)
    return examples


def pick_examples(brief: Brief, examples: list[dict], limit: int = 3) -> list[dict]:
    """Prefer examples in the same language, then the same length."""
    def score(ex: dict) -> int:
        return (2 if ex.get("language") == brief.language else 0) + (
            1 if ex.get("length") == brief.length else 0
        )

    return sorted(examples, key=score, reverse=True)[:limit]


def _format_example(ex: dict) -> str:
    b = ex["brief"]
    quals = "; ".join(b.get("qualities", []))
    return (
        f"BRIEF: product={b.get('product', '')} | audience={b.get('audience', '')} | "
        f"qualities={quals} | offer={b.get('offer') or 'none'} | "
        f"language={ex.get('language', '')} | length={ex.get('length', '')}\n"
        f"SCRIPT: {ex['script']}"
    )


def build_prompt(
    brief: Brief,
    rules: str | None = None,
    examples: list[dict] | None = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt)."""
    rules = load_rules() if rules is None else rules
    examples = pick_examples(brief, load_examples() if examples is None else examples)
    lo, hi = LENGTHS.get(brief.length, LENGTHS["30 seconds"])

    system = [
        "You are an expert short-video script writer. You write voiceover scripts for "
        "small businesses, following the expert's rules exactly.",
        "",
        "RULES:",
        rules or "(no rules file found - use a question hook, then benefits, then offer and call to action)",
    ]
    if examples:
        system += [
            "",
            "REFERENCE EXAMPLES (learn the structure and rhythm, never copy the wording "
            "or reuse their facts):",
            "\n\n".join(_format_example(e) for e in examples),
        ]
    system += [
        "",
        "OUTPUT FORMAT:",
        f"Write exactly {brief.versions} different script version(s). "
        f"Put the line {VERSION_SEPARATOR} between versions. "
        "Output only the scripts themselves: no titles, numbering, notes or explanations.",
    ]

    lines = [
        f"Product / service: {brief.product.strip()}",
        f"Target audience: {brief.audience.strip()}",
        "Key qualities:",
        *[f"- {q}" for q in brief.qualities_clean],
        f"Offer: {brief.offer.strip() or 'none given - do not invent one; end with a call to action only'}",
        f"Language: {brief.language}. {LANGUAGES.get(brief.language, '')}",
        f"Length: about {lo}-{hi} words ({brief.length} when spoken).",
        f"Tone: {brief.tone}",
        f"Platform: {brief.platform}",
    ]
    if brief.avoid.strip():
        lines.append(f"Words or claims to avoid: {brief.avoid.strip()}")
    if brief.extra.strip():
        lines.append(f"Extra notes from the buyer: {brief.extra.strip()}")
    lines += ["", "Write the script(s) now."]
    return "\n".join(system), "\n".join(lines)


def parse_versions(text: str) -> list[str]:
    parts = [p.strip() for p in text.split(VERSION_SEPARATOR)]
    parts = [p for p in parts if p]
    return parts or ([text.strip()] if text.strip() else [])


def word_count(text: str) -> int:
    return len(text.split())
