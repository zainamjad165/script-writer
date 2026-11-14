"""Automatic quality checks on generated copy.

Only things that can be verified by code are checked. Each message is a plain
sentence meant to be shown to the person using the app. An empty list means
every check passed.
"""
from __future__ import annotations

import re

from prompt import SHOT_BY_SHOT, Brief, get_copy_type, limit_warnings, resolve_format

_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_TWO_TO_NINETEEN = "|".join(k for k in _UNITS if k != "one")
_TENS_RE = "|".join(_TENS)
_BELOW_100 = rf"(?:(?:{_TENS_RE})(?:[\s-](?:one|{_TWO_TO_NINETEEN}))?|(?:{_TWO_TO_NINETEEN}))"
_HUNDREDS = rf"(?:(?:one|{_TWO_TO_NINETEEN})\s+hundred(?:\s+(?:and\s+)?{_BELOW_100})?)"
# A lone "one" is left alone on purpose: "no one", "one clear call to action"
SPELLED_NUMBER_RE = re.compile(rf"\b(?:{_HUNDREDS}|{_BELOW_100})\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"(\d)\s*(?:percent|per cent)\b", re.IGNORECASE)

THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
WORD_RE = re.compile(r"[a-z]{3,}")

TOLERANCE = 0.15            # word counts may be 15% outside the target range
MAX_HOOK_WORDS = 14         # rules say 12; allow a little slack
FACEBOOK_HEADLINE_LIMIT = 40
PRODUCT_TITLE_LIMIT = 70

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
SENTENCE_END_RE = re.compile(r"[.!?؟۔]")
LABEL_NUMBER_RE = re.compile(r"^\s*(HEADLINE|DESCRIPTION)\s*\d+\s*:", re.IGNORECASE | re.MULTILINE)
SEGMENT_RE = re.compile(r"^\s*(\d+)\s*[-–—]\s*(\d+)\s*s\b", re.IGNORECASE | re.MULTILINE)
TIMESTAMP_RE = re.compile(r"\b\d+\s*[-–—]\s*\d+\s*s(?:ec(?:onds?)?)?\b", re.IGNORECASE)
PRICE_RE = re.compile(
    r"[$₨£€]\s?\d[\d,.]*|\brs\.?\s?\d[\d,.]*|\b\d[\d,.]*\s*(?:dollars|rupees|pkr|usd)\b",
    re.IGNORECASE)
# Openings that every ad starts with. Only checked for English copy.
CLICHE_OPENERS = ("tired of", "sick of", "are you tired", "looking for", "say goodbye",
                  "introducing", "meet the", "imagine", "ever wondered", "did you know",
                  "are you ready")
# Claims the buyer never made. A phrase is fine if the buyer's own words contain it.
TIME_CLAIM_RE = re.compile(
    r"\b(?:full|whole|entire)\s+(?:week|month|year)s?\b|\ball\s+(?:week|month|year)\b"
    r"|\b(?:a|one|two|three|several)\s+(?:week|month|year)s?\b|\b(?:lifetime|forever)\b",
    re.IGNORECASE)
HEALTH_CLAIM_RE = re.compile(
    r"\b(?:healthy|healthier|health|cures?|cured|heals?|immunity|detox|sehatmand|sehat|shifa)\b",
    re.IGNORECASE)
ORIGIN_CLAIM_RE = re.compile(
    r"\b(?:grandmother|grandma|dadi|nani|family recipe|secret recipe|ancient)\b", re.IGNORECASE)
EM_DASH = "\u2014"

STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
             "it", "its", "you", "your", "that", "this", "at", "by", "as", "be", "can", "from"}
# Things that sound like an offer. Flagged only when the buyer gave none.
OFFER_PATTERNS = {
    "a percentage": re.compile(r"\d+\s*%"),
    "'free'": re.compile(r"\bfree\b"),
    "'discount'": re.compile(r"\bdiscount\b"),
    "'sale'": re.compile(r"\bsale\b"),
    "'muft'": re.compile(r"\bmuft\b"),
}


def _spelled_to_int(phrase: str) -> int:
    total = 0
    for token in re.split(r"[\s-]+", phrase.lower()):
        if token == "and":
            continue
        if token == "hundred":
            total = max(total, 1) * 100
        else:
            total += _UNITS.get(token) or _TENS[token]
    return total


def normalize_numbers(text: str) -> str:
    """'twenty percent' -> '20%', 'thirty-two' -> '32', so numbers compare fairly."""
    text = SPELLED_NUMBER_RE.sub(lambda m: str(_spelled_to_int(m.group(0))), text)
    return PERCENT_RE.sub(r"\1%", text)


def _numeric(text: str) -> str:
    """Spelled-out numbers to digits, and '43,000' to '43000' so both spellings match."""
    return THOUSANDS_RE.sub("", normalize_numbers(text))


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
    return " ".join([brief.product, brief.audience, *brief.qualities_clean,
                     *brief.pain_points_clean, brief.offer, brief.extra, brief.keywords,
                     brief.avoid, brief.shots, brief.cta])


def _shot_lines(text: str, label: str) -> list:
    return [m.group(1).strip() for m in
            re.finditer(rf"^\s*{label}\s*:\s*(.*)$", text, re.IGNORECASE | re.MULTILINE)]


def is_shot_list(brief: Brief) -> bool:
    ct = get_copy_type(brief.copy_type)
    return ct.key == "script" and resolve_format(ct, brief) == SHOT_BY_SHOT


def spoken_text(text: str, brief: Brief) -> str:
    """The words a viewer hears: the voiceover lines of a shot list, otherwise the whole text."""
    if is_shot_list(brief):
        return " ".join(_shot_lines(text, "VOICEOVER"))
    return text


def _seconds(length: str) -> int:
    m = re.match(r"\s*(\d+)\s*sec", length or "", re.IGNORECASE)
    return int(m.group(1)) if m else 0


def shot_list_problems(text: str, brief: Brief) -> list:
    segments = [(int(a), int(b)) for a, b in SEGMENT_RE.findall(text)]
    if not segments:
        return ["It isn't a timestamped shot list (no segments like '0-3s')."]
    problems = []
    if segments[0][0] != 0:
        problems.append("The timeline doesn't start at 0s.")
    elif segments[0][1] > 4:
        problems.append(f"The hook segment runs {segments[0][1]}s. Keep it to 3-4s.")
    if any(end <= start for start, end in segments):
        problems.append("A segment ends before it starts.")
    elif any(segments[i][0] != segments[i - 1][1] for i in range(1, len(segments))):
        problems.append("The timestamps have a gap or overlap between segments.")
    target = _seconds(brief.length)
    if target and abs(segments[-1][1] - target) > 1:
        problems.append(f"The timeline ends at {segments[-1][1]}s, but the reel is {target}s long.")
    if (len(_shot_lines(text, "VISUAL")) != len(segments)
            or len(_shot_lines(text, "VOICEOVER")) != len(segments)):
        problems.append("Some segments are missing a VISUAL or VOICEOVER line.")
    return problems


def _tokens(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


def copied_phrases(spoken: str, brief: Brief, n: int = 4) -> list:
    """Runs of n words repeated straight from the buyer's spec lines (numbers don't count)."""
    source = _tokens(" ".join([*brief.qualities_clean, brief.extra]))
    heard = _tokens(spoken)
    source_grams = {tuple(source[i:i + n]) for i in range(len(source) - n + 1)}
    found = []
    for i in range(len(heard) - n + 1):
        gram = tuple(heard[i:i + n])
        if (gram in source_grams and not any(t.isdigit() for t in gram)
                and not all(t in STOPWORDS for t in gram)):
            phrase = " ".join(gram)
            if not any(phrase in f or f in phrase for f in found):
                found.append(phrase)
    return found


def copy_text(text: str, brief: Brief) -> str:
    """The wording a customer reads or hears (shot-list visuals and timestamps removed)."""
    if is_shot_list(brief):
        text = "\n".join(l for l in text.splitlines() if not re.match(r"\s*VISUAL\s*:", l, re.I))
    return TIMESTAMP_RE.sub("", text)


def unsupported_claims(text: str, brief: Brief) -> list:
    """Time spans, health benefits and origin stories the buyer did not state.

    'Keeps cold for 24 hours' must not become 'cold for a full week'. A claim passes when the
    same words appear in the buyer's own text (offer and call to action included)."""
    given = _input_text(brief).lower()
    found = []
    for rx in (TIME_CLAIM_RE, HEALTH_CLAIM_RE, ORIGIN_CLAIM_RE):
        for m in rx.finditer(copy_text(text, brief)):
            phrase = m.group(0).lower()
            if phrase not in given and phrase not in found:
                found.append(phrase)
    return found


def _opening(text: str, brief: Brief, platform: str) -> str:
    ct = get_copy_type(brief.copy_type)
    if ct.key == "script":
        return (_shot_lines(text, "VOICEOVER") or [""])[0] if is_shot_list(brief) else text
    if ct.key == "caption":
        return text
    if ct.key == "ad" and platform != "Google search ad":
        return _line_value(text, "PRIMARY TEXT")
    return ""


def missing_qualities(text: str, brief: Brief) -> list:
    """Key qualities that do not seem to appear in the text.

    A quality with numbers counts as present when at least one of its numbers appears. A
    word-only quality counts as present when at least one of its main words appears (matched
    on the first 4 letters, so 'leak-proof' matches 'leaks'). The test is deliberately loose
    so that a quality said in the customer's own words is not flagged. Word-only qualities
    are not checked when the copy is not in English, because a translation would look
    'missing' to this simple test."""
    numeric_text = _numeric(text).lower()
    text_numbers = set(NUMBER_RE.findall(numeric_text))
    text_prefixes = {w[:4] for w in WORD_RE.findall(numeric_text)}
    english = brief.language == "English"
    missing = []
    for quality in brief.qualities_clean:
        q = _numeric(quality).lower()
        numbers = NUMBER_RE.findall(q)
        if numbers:
            covered = any(n in text_numbers for n in numbers)
        elif english:
            words = [w for w in WORD_RE.findall(q) if len(w) >= 4]
            covered = not words or any(w[:4] in text_prefixes for w in words)
        else:
            covered = True
        if not covered:
            missing.append(quality if len(quality) <= 40 else quality[:37] + "...")
    return missing


def run_checks(text: str, brief: Brief, relax: str = "") -> list:
    """relax="shorter" ignores a too-short result, relax="longer" ignores a too-long one
    (used after the user deliberately asked for a shorter or longer version)."""
    ct = get_copy_type(brief.copy_type)
    platform = brief.platform if brief.platform in ct.platforms else ct.platforms[0]
    out: list = []
    normalized = _numeric(text)               # spelled-out numbers become digits
    lowered = normalized.lower()
    given = _numeric(_input_text(brief))

    # --- structure -------------------------------------------------------
    shot = is_shot_list(brief)
    spoken = spoken_text(text, brief)
    if ct.key == "script":
        if shot:
            out += shot_list_problems(text, brief)
        else:
            m = SENTENCE_END_RE.search(text)
            first = text[: m.end()] if m else text
            if not first.strip().endswith(("?", "؟")):
                out.append("The opening isn't a question. The expert's structure starts with one.")
            elif len(first.split()) > MAX_HOOK_WORDS:
                out.append(f"The opening question is {len(first.split())} words. Aim for 12 or fewer.")
        if EMOJI_RE.search(text):
            out.append("It contains emojis, but a voiceover script should be plain text.")
    if brief.language == "English":
        opening = _opening(text, brief, platform).lower().lstrip(" \"'“‘([#")
        for phrase in CLICHE_OPENERS:
            if opening.startswith(phrase):
                out.append(f"The opening ('{phrase}...') is a cliché. Start with something "
                           "specific the viewer can picture.")
                break

    # --- length ----------------------------------------------------------
    is_google = ct.key == "ad" and platform == "Google search ad"
    target = ct.word_ranges.get(brief.length)
    if target and not is_google:
        lo, hi = target
        n = _words(spoken if ct.key == "script" else _body(text, ct.key, platform))
        too_short = n < lo * (1 - TOLERANCE) and relax != "shorter"
        too_long = n > hi * (1 + TOLERANCE) and relax != "longer"
        if too_short or too_long:
            out.append(f"It has {n} words, but the target is {lo}-{hi}.")

    # --- every key quality should appear (the expert's main feedback) -------
    skip_coverage = is_google or (ct.key == "caption" and brief.length == "Short")
    if not skip_coverage:
        missing = missing_qualities(text, brief)
        if missing:
            out.append("These key qualities may be missing: " + "; ".join(missing) + ".")

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
    unlabeled = TIMESTAMP_RE.sub("", LABEL_NUMBER_RE.sub("", normalized))  # labels, not facts
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
            if not all(d in normalized for d in digits):
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

    if ct.key == "script":
        allowed = set(NUMBER_RE.findall(_numeric(brief.offer + " " + brief.cta)))
        spoken_prices = [p for p in PRICE_RE.findall(_numeric(spoken))
                         if not (set(NUMBER_RE.findall(p)) & allowed)]
        if spoken_prices:
            out.append(f"A price is read out loud ({spoken_prices[0].strip()}). Put prices and "
                       "discounts in on-screen text; keep the voiceover to the offer and the call to action.")
        copied = copied_phrases(spoken, brief)
        if copied:
            quoted = "; ".join(f"'{c}'" for c in copied[:2])
            out.append(f"It repeats phrases straight from your spec lines ({quoted}). "
                       "Say what the customer sees or feels instead.")

    claims = unsupported_claims(text, brief)
    if claims:
        out.append("It adds claims your brief doesn't support (" + ", ".join(f"'{c}'" for c in claims[:3])
                   + "). Remove them or check they are true.")
    if EM_DASH in TIMESTAMP_RE.sub("", text):
        out.append("It contains an em dash (\u2014), a common sign of AI writing. Use a comma or a full stop.")

    avoid_terms = [t.strip().lower() for t in re.split(r"[,;\n]", brief.avoid) if t.strip()]
    hits = [t for t in avoid_terms if t in lowered]
    if hits:
        out.append("It contains words you asked to avoid: " + ", ".join(hits) + ".")

    return out
