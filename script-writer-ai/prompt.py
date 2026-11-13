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

TONES = ["Friendly", "High-energy / punchy", "Professional", "Funny", "Luxury / premium",
         "Urgent / exciting", "Emotional"]


VO_ONLY = "Voiceover only"
SHOT_BY_SHOT = "Shot-by-shot (timestamps)"

_SHOT_FORMAT = (
    "A timestamped shot list that runs back to back from 0s to the full length "
    "(3-4 segments for 15 seconds, 4-6 for 30 seconds, 6-9 for 60 seconds). "
    "Write every segment with exactly these labeled lines:\n"
    "0-3s\n"
    "VISUAL: (what the camera shows; only things that can realistically be filmed)\n"
    "VOICEOVER: (what is said out loud: one or two short, natural spoken sentences)\n"
    "ON-SCREEN TEXT: (1-5 words; put prices and discounts here, not in the voiceover)\n"
    "The first segment (0-3s) is the hook: a strong visual plus a spoken line that stops "
    "the scroll. The last segment is the call to action."
)


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
    word_ranges: dict = field(default_factory=dict)  # length label -> (min, max) words
    formats: dict = field(default_factory=dict)      # format label -> exact output format
    angles: dict = field(default_factory=dict)       # "*" or a format label -> tuple of angles
    supports_cta: bool = False                       # show the "exact call to action" box

    def format_for(self, platform: str, fmt: str = "") -> str:
        if fmt in self.formats:
            return self.formats[fmt]
        return self.output_format.get(platform, self.output_format["*"])

    def angles_for(self, fmt: str = "") -> tuple:
        return self.angles.get(fmt) or self.angles.get("*", ())


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
        word_ranges={"15 seconds": (35, 45), "30 seconds": (70, 85), "60 seconds": (140, 170)},
        formats={
            VO_ONLY: "The spoken voiceover text only, as plain paragraph(s).",
            SHOT_BY_SHOT: _SHOT_FORMAT,
        },
        angles={
            "*": (
                "Open with a question that dares or tests the viewer, something they can picture right away.",
                "Open with a question that describes the exact annoying moment in the viewer's own words.",
                "Open with a question that challenges something the viewer takes for granted.",
            ),
            SHOT_BY_SHOT: (
                "Challenge or demo: the opening visual is a test or a dare, and the first spoken line is a confident statement or question.",
                "Real-life moment: open mid-scene on the annoying situation, with a spoken line in the viewer's own words.",
                "Bold claim: open on a striking visual with a confident, slightly provocative spoken line, then prove it.",
            ),
        },
        supports_cta=True,
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
        word_ranges={"Short": (1, 30), "Medium": (40, 70), "Long": (90, 150)},
        angles={"*": (
            "A short personal story or confession that leads to the product.",
            "A direct question to the reader about their situation.",
            "A bold one-line statement, then the proof.",
        )},
        supports_cta=True,
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
        word_ranges={"Short": (20, 30), "Medium": (40, 60)},
        angles={"*": (
            "Pain first: start with the problem, then the fix.",
            "Benefit first: start with the best result the customer gets.",
            "Proof first: start with the strongest fact from the brief.",
        )},
        supports_cta=True,
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
        word_ranges={"Short": (40, 60), "Standard": (80, 120), "Long": (150, 200)},
        angles={"*": (
            "Benefit-led: open with the main benefit.",
            "Use-case-led: open with a short moment of everyday use.",
            "Plain-language specs: open with the most important fact, explained simply.",
        )},
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
    format: str = ""                                   # e.g. "Shot-by-shot (timestamps)"
    pain_points: list = field(default_factory=list)    # problems the product solves
    shots: str = ""                                    # shots the buyer can film
    cta: str = ""                                      # exact call to action, if given
    qualities_clean: list = field(init=False, default_factory=list)
    pain_points_clean: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.qualities_clean = [q.strip() for q in self.qualities if q.strip()]
        self.pain_points_clean = [q.strip() for q in self.pain_points if q.strip()]

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


def resolve_format(ct: CopyType, brief: Brief) -> str:
    """The chosen output format label, or '' for types that have only one."""
    if not ct.formats:
        return ""
    return brief.format if brief.format in ct.formats else next(iter(ct.formats))


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
    """Same copy type (and output format) only; prefer the same language, then the same length."""
    ct = get_copy_type(brief.copy_type)
    fmt = resolve_format(ct, brief)
    first_format = next(iter(ct.formats), "")
    same_type = [
        e for e in examples
        if e.get("type", "script") == brief.copy_type
        and (not ct.formats or e.get("format", first_format) == fmt)
    ]

    def score(ex: dict) -> int:
        return (2 if ex.get("language") == brief.language else 0) + (
            1 if ex.get("length") == brief.length else 0
        )

    return sorted(same_type, key=score, reverse=True)[:limit]


def _format_example(ex: dict) -> str:
    b = ex["brief"]
    quals = "; ".join(b.get("qualities", []))
    pains = "; ".join(b.get("pain_points", []))
    extras = (f" | problems it solves={pains}" if pains else "") + (
        f" | shots available={b['shots']}" if b.get("shots") else "")
    return (
        f"BRIEF: product={b.get('product', '')} | audience={b.get('audience', '')} | "
        f"qualities={quals} | offer={b.get('offer') or 'none'} | "
        f"language={ex.get('language', '')} | length={ex.get('length', '')}{extras}\n"
        f"OUTPUT:\n{ex['script']}"
    )


def _brief_lines(brief: Brief, ct: CopyType, platform: str, length_text: str) -> list:
    lines = [
        f"Copy type: {ct.label}",
        f"Product / service: {brief.product.strip()}",
        f"Target audience: {brief.audience.strip()}",
        "Key qualities (ALL must appear in the copy):",
        *[f"- {q}" for q in brief.qualities_clean],
        *(["Problems it solves (use them for the hook: show the problem, don't just name it):",
           *[f"- {p}" for p in brief.pain_points_clean]] if brief.pain_points_clean else []),
        f"Offer: {brief.offer.strip() or 'none given - do not invent one; end with a call to action only'}",
        f"Language: {brief.language}. {LANGUAGES.get(brief.language, '')}",
        f"Length: {length_text}",
        f"Tone: {brief.tone}",
        f"Platform: {platform}",
    ]
    fmt = resolve_format(ct, brief)
    if fmt:
        lines.append(f"Format: {fmt}")
    if fmt == SHOT_BY_SHOT and brief.shots.strip():
        lines.append(f"Shots the buyer can film (use only these kinds of visuals): {brief.shots.strip()}")
    if brief.cta.strip() and ct.supports_cta:
        lines.append(f"Call to action to end with (keep its meaning and any offer in it): {brief.cta.strip()}")
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
        lines.append(
            f"Extra notes from the buyer (secondary facts, use only if there is space): "
            f"{brief.extra.strip()}")
    return lines


def build_prompt(brief: Brief, rules: str | None = None, examples: list | None = None) -> tuple:
    """Return (system_prompt, user_prompt)."""
    ct = get_copy_type(brief.copy_type)
    rules = load_rules(ct.key) if rules is None else rules
    examples = pick_examples(brief, load_examples() if examples is None else examples)
    length_text = ct.lengths.get(brief.length, ct.lengths[ct.default_length])
    platform = brief.platform if brief.platform in ct.platforms else ct.platforms[0]
    fmt = resolve_format(ct, brief)
    angles = ct.angles_for(fmt)
    angle_text = ""
    if angles:
        listed = " ".join(f"Version {i + 1}: {angles[i % len(angles)]}" for i in range(brief.versions))
        angle_text = (
            "Give each version its own angle and structure (do not just swap synonyms): "
            f"{listed} ")

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
        ct.format_for(platform, fmt),
        "",
        f"Write exactly {brief.versions} version(s). EVERY version must include ALL of the key "
        "qualities listed in the brief, but say them as what the customer sees, feels or does, "
        "never as a spec list. Make the versions differ in hook, angle and wording, "
        "never in which key qualities they cover. " + angle_text +
        "Use the extra notes only if there is space. "
        f"Put the line {VERSION_SEPARATOR} between versions. "
        "Output only the copy itself: no version numbers, notes or explanations.",
    ]

    lines = _brief_lines(brief, ct, platform, length_text)
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


# ---------- refining an existing version ----------
REFINE_ACTIONS = {
    "Make it shorter": (
        "Make it clearly shorter (about 25% fewer words) without losing the offer, "
        "the call to action or the key benefits."
    ),
    "Make it longer": (
        "Make it about 25% longer by using more of the key qualities from the brief. "
        "Do not add any facts that are not in the brief."
    ),
    "Sound less like a spec sheet": (
        "Rewrite it so it sounds like a person talking. Replace any phrases copied from the "
        "brief's specs with what the customer sees, feels or does. Keep every fact and the offer."
    ),
    "Include all key qualities": (
        "Make sure EVERY key quality from the brief appears in the copy, while staying within "
        "the length target. Keep the hook and the offer."
    ),
    "Try a different hook": (
        "Keep everything else, but replace the opening hook with a different one "
        "(use the same kind of opening the rules ask for)."
    ),
    "Change the tone": "",    # needs the new tone
    "Custom change": "",      # needs the user's own words
}


def refine_instruction(action: str, tone: str = "", custom: str = "") -> str:
    """Turn the chosen refine action into an instruction. Empty means 'incomplete'."""
    if action == "Change the tone":
        return f"Rewrite it in a {tone} tone. Keep all facts and the structure." if tone else ""
    if action == "Custom change":
        return custom.strip()
    return REFINE_ACTIONS.get(action, "")


def build_refine_prompt(brief: Brief, original: str, instruction: str,
                        rules: str | None = None) -> tuple:
    """Return (system_prompt, user_prompt) for revising one existing version."""
    ct = get_copy_type(brief.copy_type)
    rules = load_rules(ct.key) if rules is None else rules
    platform = brief.platform if brief.platform in ct.platforms else ct.platforms[0]
    length_text = ct.lengths.get(brief.length, ct.lengths[ct.default_length])
    system = [
        f"You are an expert copywriter revising existing {ct.label.lower()}. "
        "Follow the expert's rules exactly.",
        "",
        "RULES:",
        rules or "(no rules file found - be clear, concrete and benefit-led)",
        "",
        "OUTPUT FORMAT:",
        ct.format_for(platform, resolve_format(ct, brief)),
        "",
        "Apply ONLY the requested change. Keep every fact, the offer and the call to action "
        "unless the change says otherwise. Never add facts, numbers or offers that are not in "
        "the brief or the original. Output exactly ONE revised version and nothing else: "
        "no notes or explanations.",
    ]
    user = [
        "ORIGINAL COPY:",
        original.strip(),
        "",
        "REQUESTED CHANGE:",
        instruction.strip(),
        "",
        "BRIEF (for reference):",
        *_brief_lines(brief, ct, platform, length_text),
        "",
        "Write the revised copy now.",
    ]
    return "\n".join(system), "\n".join(user)


_FIX_GUIDANCE = (
    "If a number is not in the brief, remove it or replace it with a fact from the brief. "
    "If the offer is missing, include it exactly as given. "
    "If a key quality is missing, work it in without dropping any other one. "
    "Respect the length target and every character limit."
)

# Refine actions that deliberately move the length away from the target
REFINE_RELAX = {"Make it shorter": "shorter", "Make it longer": "longer"}


def fix_instruction(problems: list) -> str:
    """Turn the automatic checks' complaints into a revision instruction."""
    listed = "\n".join(f"- {p}" for p in problems)
    return (
        "An automatic check found these problems. Fix ONLY these and keep everything else "
        "as it is:\n" + listed + "\n" + _FIX_GUIDANCE
    )


def build_batch_fix_prompt(brief: Brief, items: list, keep: str = "",
                           rules: str | None = None) -> tuple:
    """Fix several versions in ONE request. items = [(text, [problems]), ...].
    The AI must answer with the same number of versions, in the same order."""
    ct = get_copy_type(brief.copy_type)
    rules = load_rules(ct.key) if rules is None else rules
    platform = brief.platform if brief.platform in ct.platforms else ct.platforms[0]
    length_text = ct.lengths.get(brief.length, ct.lengths[ct.default_length])
    n = len(items)
    system = [
        f"You are an expert copywriter fixing {ct.label.lower()}. Follow the expert's rules exactly.",
        "",
        "RULES:",
        rules or "(no rules file found - be clear, concrete and benefit-led)",
        "",
        "OUTPUT FORMAT (for each version):",
        ct.format_for(platform, resolve_format(ct, brief)),
        "",
        f"You will receive {n} version(s). Each has problems found by an automatic check. "
        "Fix ONLY the listed problems in each one and keep everything else as it is. "
        f"{_FIX_GUIDANCE} Never add facts, numbers or offers that are not in the brief or the "
        f"original. Answer with exactly {n} revised version(s), in the same order, with the line "
        f"{VERSION_SEPARATOR} between them. No numbering, notes or explanations.",
    ]
    if keep.strip():
        system.append(
            f"The copy was just deliberately revised on request ({keep.strip()}). "
            "Do not undo that change."
        )
    user = []
    for i, (text, problems) in enumerate(items, start=1):
        user += [f"VERSION {i}:", text.strip(), "PROBLEMS:", *[f"- {p}" for p in problems], ""]
    user += ["BRIEF (for reference):", *_brief_lines(brief, ct, platform, length_text), "",
             "Write the revised version(s) now."]
    return "\n".join(system), "\n".join(user)


def length_hint(ct: CopyType, length: str) -> str:
    """Label for the length picker, e.g. '30 seconds (~70-85 words)'."""
    rng = ct.word_ranges.get(length)
    if not rng:
        return length
    lo, hi = rng
    return f"{length} (up to ~{hi} words)" if lo <= 1 else f"{length} (~{lo}-{hi} words)"
