"""Automatic quality checks on generated copy.

Only things that can be verified by code are checked. Each message is a plain
sentence meant to be shown to the person using the app. An empty list means
every check passed.
"""
from __future__ import annotations

import re

from prompt import Brief, get_copy_type, limit_warnings

TOLERANCE = 0.15            # word counts may be 15% outside the target range
MAX_HOOK_WORDS = 14         # rules say 12; allow a little slack
FACEBOOK_HEADLINE_LIMIT = 40
PRODUCT_TITLE_LIMIT = 70

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
SENTENCE_END_RE = re.compile(r"[.!?؟۔]")
LABEL_NUMBER_RE = re.compile(r"^\s*(HEADLINE|DESCRIPTION)\s*\d+\s*:", re.IGNORECASE | re.MULTILINE)
# Things that sound like an offer. Flagged only when the buyer gave none.
OFFER_PATTERNS = {
    "a percentage": re.compile(r"\d+\s*%"),
    "'free'": re.compile(r"\bfree\b"),
    "'discount'": re.compile(r"\bdiscount\b"),
    "'sale'": re.compile(r"\bsale\b"),
    "'muft'": re.compile(r"\bmuft\b"),
}


def _line_value(text: str, label: str) -> str:
    m = re.search(rf"^\s*{label}\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _body(text: str, copy_type: str, platform: str) -> str:
    """The part of the output that the word-count target applies to."""
    if copy_type == "ad":
        m = re.search(r"PRIMARY TEXT\s*:\s*(.+?)(?:^\s*CALL TO ACTION\s*:|\Z)", text,
                      re.IGNORECASE | re.DOTALL | re.MULTILINE)
        return m.group(1).strip() if m else text
    if copy_type == "product":
        m = re.search(r"DESCRIPTION\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
        body = m.group(1) if m else text
        return "\n".join(l for l in body.splitlines() if not l.strip().startswith("- ")).strip()
    return text


def _words(text: str) -> int:
    return len([w for w in text.split() if not w.startswith("#")])


def _input_text(brief: Brief) -> str:
    return " ".join([brief.product, brief.audience, *brief.qualities_clean, brief.offer,
                     brief.extra, brief.keywords, brief.avoid])


def run_checks(text: str, brief: Brief) -> list:
    ct = get_copy_type(brief.copy_type)
    platform = brief.platform if brief.platform in ct.platforms else ct.platforms[0]
    out: list = []
    lowered = text.lower()
    given = _input_text(brief)

    # --- structure -------------------------------------------------------
    if ct.key == "script":
        m = SENTENCE_END_RE.search(text)
        first = text[: m.end()] if m else text
        if not first.strip().endswith(("?", "؟")):
            out.append("The opening isn't a question. The expert's structure starts with one.")
        elif len(first.split()) > MAX_HOOK_WORDS:
            out.append(f"The opening question is {len(first.split())} words. Aim for 12 or fewer.")
        if EMOJI_RE.search(text):
            out.append("It contains emojis, but a voiceover script should be plain text.")

    # --- length ----------------------------------------------------------
    is_google = ct.key == "ad" and platform == "Google search ad"
    target = ct.word_ranges.get(brief.length)
    if target and not is_google:
        lo, hi = target
        n = _words(_body(text, ct.key, platform))
        if n < lo * (1 - TOLERANCE) or n > hi * (1 + TOLERANCE):
            out.append(f"It has {n} words, but the target is {lo}-{hi}.")

    # --- hard limits -----------------------------------------------------
    out += limit_warnings(text, ct.key, platform)
    if ct.key == "ad" and not is_google:
        headline = _line_value(text, "HEADLINE")
        if len(headline) > FACEBOOK_HEADLINE_LIMIT:
            out.append(f"The headline is {len(headline)} characters (limit {FACEBOOK_HEADLINE_LIMIT}).")
    if ct.key == "product":
        title = _line_value(text, "TITLE")
        if len(title) > PRODUCT_TITLE_LIMIT:
            out.append(f"The title is {len(title)} characters (limit {PRODUCT_TITLE_LIMIT}).")

    # --- toggles the buyer chose ----------------------------------------
    def on(key: str) -> bool:
        return brief.toggles.get(key, ct.toggles[key].default)

    if ct.key == "caption":
        has_tags = "#" in text
        if on("hashtags") and not has_tags:
            out.append("Hashtags were requested but none were added.")
        if not on("hashtags") and has_tags:
            out.append("Hashtags were switched off but the text contains some.")
        if not on("emojis") and EMOJI_RE.search(text):
            out.append("Emojis were switched off but the text contains some.")
    if ct.key == "product":
        has_bullets = any(l.strip().startswith("- ") for l in text.splitlines())
        if on("bullets") and not has_bullets:
            out.append("Bullet highlights were requested but none were added.")
        if not on("bullets") and has_bullets:
            out.append("Bullet highlights were switched off but the text contains some.")

    # --- honesty: the brief is the only source of facts -------------------
    unlabeled = LABEL_NUMBER_RE.sub("", text)  # "HEADLINE 1:" is a label, not a fact
    extra_numbers = sorted(set(NUMBER_RE.findall(unlabeled)) - set(NUMBER_RE.findall(given)),
                           key=lambda x: float(x.replace(",", ".")))
    if extra_numbers:
        out.append("It uses numbers that aren't in your brief (" + ", ".join(extra_numbers)
                   + "). Check they are true.")

    offer = brief.offer.strip()
    if offer:
        digits = NUMBER_RE.findall(offer)
        words = [t for t in re.findall(r"\w+", offer.lower()) if len(t) > 2]
        if digits:
            if not all(d in text for d in digits):
                out.append(f"Your offer ('{offer}') seems to be missing.")
        elif brief.language == "English" and words:
            found = sum(1 for w in words if w in lowered)
            if found < len(words) / 2:
                out.append(f"Your offer ('{offer}') seems to be missing.")
    else:
        found_kinds = [name for name, rx in OFFER_PATTERNS.items()
                       if rx.search(lowered) and not rx.search(given.lower())]
        if found_kinds:
            out.append("You gave no offer, but the text mentions " + ", ".join(found_kinds)
                       + ". Remove it unless it's real.")

    avoid_terms = [t.strip().lower() for t in re.split(r"[,;\n]", brief.avoid) if t.strip()]
    hits = [t for t in avoid_terms if t in lowered]
    if hits:
        out.append("It contains words you asked to avoid: " + ", ".join(hits) + ".")

    return out
