"""Builds the prompt for each copy type (script, caption, ad, product description)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).parent
RULES_FILE = BASE_DIR / "rules.md"          # general rules for every copy type
RULES_DIR = BASE_DIR / "rules"              # one extra rules file per copy type
EXAMPLES_DIR = BASE_DIR / "examples"

VERSION_SEPARATOR = "===VERSION==="

LANGUAGES = {
    "English": "Write in simple, natural English.",
    "Roman Urdu": (
        "Write in Roman Urdu: Urdu written with English letters, the way people in "
        "Pakistan speak and text. Natural and conversational, not a stiff translation. "
        "Common English words (order, delivery, link) are fine."
    ),
    "Urdu (اردو)": (
        "Write in Urdu using Urdu script. Natural Urdu, not a stiff translation. "
        "Common English words (order, delivery) may stay in English."
    ),
}

TONES = ["Friendly", "Professional", "Funny", "Luxury / premium", "Urgent / exciting", "Emotional"]


@dataclass(frozen=True)
class Toggle:
    label: str
    default: bool
    when_on: str
    when_off: str = ""


@dataclass(frozen=True)
class CopyType:
    key: str
    label: str            # shown in the type picker
    noun: str             # "script", "caption"... used in button text and headings
    lengths: dict         # length label -> instruction given to the model
    default_length: str
    platforms: list
    output_format: dict   # platform -> exact output format; "*" is the fallback
    toggles: dict = field(default_factory=dict)
    keywords_label: str = ""   # if set, the form shows a keywords box with this label
    length_label: str = "Length"

    def format_for(self, platform: str) -> str:
        return self.output_format.get(platform, self.output_format["*"])


_FB_AD_FORMAT = (
    "Use exactly these labeled lines for each version:\n"
    "HEADLINE: (max 40 characters)\n"
    "PRIMARY TEXT: (the ad body, at the requested length)\n"
    "CALL TO ACTION: (2-4 words, e.g. Shop Now, Order Today)"
)

COPY_TYPES: dict = {
    "script": CopyType(
        key="script",
        label="Video script",
        noun="script",
        lengths={
            "15 seconds": "about 35-45 words (15 seconds when spoken)",
            "30 seconds": "about 70-85 words (30 seconds when spoken)",
            "60 seconds": "about 140-170 words (60 seconds when spoken)",
        },
        default_length="30 seconds",
        platforms=["Instagram Reels", "TikTok", "YouTube Shorts", "Facebook ad", "General video"],
        output_format={"*": "The spoken voiceover text only, as plain paragraph(s)."},
    ),
    "caption": CopyType(
        key="caption",
        label="Social media caption",
        noun="caption",
        lengths={
            "Short": "1-2 short lines (under 30 words)",
            "Medium": "3-5 short lines (about 40-70 words)",
            "Long": "a story-style caption (about 90-150 words)",
        },
        default_length="Medium",
        platforms=["Instagram", "Facebook", "TikTok", "LinkedIn"],
        output_format={"*": (
            "The finished caption, ready to paste. The first line must work as a hook, "
            "because only the first line shows before 'see more'."
        )},
        toggles={
            "hashtags": Toggle("Add hashtags", True,
                               "End with 5-8 relevant hashtags on a separate last line.",
                               "Do not use any hashtags."),
            "emojis": Toggle("Use emojis", True,
                             "Use emojis sparingly (2-4 total), only where they add meaning.",
                             "Do not use any emojis."),
        },
    ),
    "ad": CopyType(
        key="ad",
        label="Ad copy",
        noun="ad",
        lengths={
            "Short": "short primary text (about 20-30 words)",
            "Medium": "medium primary text (about 40-60 words)",
        },
        default_length="Short",
        platforms=["Facebook / Instagram ad", "Google search ad"],
        output_format={
            "*": _FB_AD_FORMAT,
            "Facebook / Instagram ad": _FB_AD_FORMAT,
            "Google search ad": (
                "Ignore any length setting. Use exactly these labeled lines for each version:\n"
                "HEADLINE 1: (HARD LIMIT 30 characters including spaces)\n"
                "HEADLINE 2: (HARD LIMIT 30 characters including spaces)\n"
                "HEADLINE 3: (HARD LIMIT 30 characters including spaces)\n"
                "DESCRIPTION 1: (HARD LIMIT 90 characters including spaces)\n"
                "DESCRIPTION 2: (HARD LIMIT 90 characters including spaces)\n"
                "Count characters carefully; going over a limit makes the ad unusable."
            ),
        },
        keywords_label="Search keywords to include (optional)",
        length_label="Length (Facebook / Instagram only)",
    ),
    "product": CopyType(
        key="product",
        label="Product description",
        noun="product description",
        lengths={
            "Short": "about 40-60 words",
            "Standard": "about 80-120 words",
            "Long": "about 150-200 words",
        },
        default_length="Standard",
        platforms=["Own website", "Daraz", "Amazon", "Instagram / Facebook shop"],
        output_format={"*": (
            "Use exactly these labeled parts for each version:\n"
            "TITLE: (a clear product title, max 70 characters)\n"
            "DESCRIPTION: (the description at the requested length)"
        )},
        toggles={
            "bullets": Toggle("Add bullet highlights", False,
                              "After the description, add 3-5 short highlight lines, each starting with '- '.",
                              "Write flowing text with no bullet points."),
        },
        keywords_label="Keywords to include naturally (optional)",
    ),
}


@dataclass
class Brief:
    product: str
    audience: str
    qualities: list
    offer: str = ""
    language: str = "English"
    length: str = ""
    tone: str = "Friendly"
    platform: str = ""
    avoid: str = ""
    extra: str = ""
    versions: int = 3
    copy_type: str = "script"
    toggles: dict = field(default_factory=dict)
    keywords: str = ""
    qualities_clean: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.qualities_clean = [q.strip() for q in self.qualities if q.strip()]

    def missing(self) -> list:
        out = []
        if not self.product.strip():
            out.append("product")
        if not self.audience.strip():
            out.append("audience")
        if not self.qualities_clean:
            out.append("qualities")
        return out


def get_copy_type(key: str) -> CopyType:
    return COPY_TYPES.get(key) or COPY_TYPES["script"]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def load_rules(copy_type: str = "script", general: Path = RULES_FILE, rules_dir: Path = RULES_DIR) -> str:
    """General rules + the rules for this copy type."""
    specific = _read(rules_dir / f"{copy_type}.md")
    parts = [p for p in (_read(general), specific) if p]
    return "\n\n".join(parts)


def load_examples(directory: Path = EXAMPLES_DIR) -> list:
    """Load every *.json file in examples/. Each file holds a list of
    {type (optional, default 'script'), language, length, brief{...}, script}.
    Bad files are skipped so one typo never breaks the app."""
    examples: list = []
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
            if not (isinstance(item, dict) and isinstance(item.get("brief"), dict)):
                continue
            text = item.get("script") or item.get("output")
            if text:
                item = dict(item, script=text)
                examples.append(item)
    return examples


def pick_examples(brief: Brief, examples: list, limit: int = 3) -> list:
    """Same copy type only; prefer the same language, then the same length."""
    same_type = [e for e in examples if e.get("type", "script") == brief.copy_type]

    def score(ex: dict) -> int:
        return (2 if ex.get("language") == brief.language else 0) + (
            1 if ex.get("length") == brief.length else 0
        )

    return sorted(same_type, key=score, reverse=True)[:limit]


def _format_example(ex: dict) -> str:
    b = ex["brief"]
    quals = "; ".join(b.get("qualities", []))
    return (
        f"BRIEF: product={b.get('product', '')} | audience={b.get('audience', '')} | "
        f"qualities={quals} | offer={b.get('offer') or 'none'} | "
        f"language={ex.get('language', '')} | length={ex.get('length', '')}\n"
        f"OUTPUT:\n{ex['script']}"
    )


def build_prompt(brief: Brief, rules: str | None = None, examples: list | None = None) -> tuple:
    """Return (system_prompt, user_prompt)."""
    ct = get_copy_type(brief.copy_type)
    rules = load_rules(ct.key) if rules is None else rules
    examples = pick_examples(brief, load_examples() if examples is None else examples)
    length_text = ct.lengths.get(brief.length, ct.lengths[ct.default_length])
    platform = brief.platform if brief.platform in ct.platforms else ct.platforms[0]

    system = [
        f"You are an expert copywriter. Today you write: {ct.label.lower()}. "
        "Follow the expert's rules exactly.",
        "",
        "RULES:",
        rules or "(no rules file found - be clear, concrete and benefit-led)",
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
        ct.format_for(platform),
        "",
        f"Write exactly {brief.versions} different version(s), each with a different angle. "
        f"Put the line {VERSION_SEPARATOR} between versions. "
        "Output only the copy itself: no version numbers, notes or explanations.",
    ]

    lines = [
        f"Copy type: {ct.label}",
        f"Product / service: {brief.product.strip()}",
        f"Target audience: {brief.audience.strip()}",
        "Key qualities:",
        *[f"- {q}" for q in brief.qualities_clean],
        f"Offer: {brief.offer.strip() or 'none given - do not invent one; end with a call to action only'}",
        f"Language: {brief.language}. {LANGUAGES.get(brief.language, '')}",
        f"Length: {length_text}",
        f"Tone: {brief.tone}",
        f"Platform: {platform}",
    ]
    for key, toggle in ct.toggles.items():
        on = brief.toggles.get(key, toggle.default)
        instruction = toggle.when_on if on else toggle.when_off
        if instruction:
            lines.append(instruction)
    if brief.keywords.strip() and ct.keywords_label:
        lines.append(f"Keywords to include naturally: {brief.keywords.strip()}")
    if brief.avoid.strip():
        lines.append(f"Words or claims to avoid: {brief.avoid.strip()}")
    if brief.extra.strip():
        lines.append(f"Extra notes from the buyer: {brief.extra.strip()}")
    lines += ["", "Write the copy now."]
    return "\n".join(system), "\n".join(lines)


def parse_versions(text: str) -> list:
    parts = [p.strip() for p in text.split(VERSION_SEPARATOR)]
    parts = [p for p in parts if p]
    return parts or ([text.strip()] if text.strip() else [])


def word_count(text: str) -> int:
    return len(text.split())


_LIMIT_RE = re.compile(r"^\s*(HEADLINE|DESCRIPTION)\s*\d*\s*:\s*(.+)$", re.IGNORECASE)


def limit_warnings(text: str, copy_type: str, platform: str) -> list:
    """Google search ads have hard character limits; AI often goes over."""
    if copy_type != "ad" or platform != "Google search ad":
        return []
    warnings = []
    for line in text.splitlines():
        m = _LIMIT_RE.match(line)
        if not m:
            continue
        limit = 30 if m.group(1).upper() == "HEADLINE" else 90
        content = m.group(2).strip()
        if len(content) > limit:
            warnings.append(
                f"{m.group(1).title()} is {len(content)} characters (limit {limit}): "
                f"\"{content[:35]}…\""
            )
    return warnings
