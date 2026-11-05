"""Automatically revise copy until it passes the quality checks (or tries run out).

Two layers, cheapest first:
1. quick_fix: plain code, no AI request (e.g. strip emojis from a voiceover script).
2. AI fixes: ALL failing versions go to the AI in ONE request per try.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from checks import EMOJI_RE, run_checks
from llm import LLMError
from prompt import Brief, build_batch_fix_prompt, get_copy_type, parse_versions

HASHTAG_RE = re.compile(r"(?<!\w)#\w+")


@dataclass
class AutoFixResult:
    text: str                       # the best version found
    attempts: int                   # AI requests this version took part in
    problems: list                  # problems still present in `text`
    original_problems: list = field(default_factory=list)
    error: str = ""                 # set if fixing stopped early (e.g. free limit reached)

    @property
    def fixed(self) -> bool:
        return bool(self.original_problems) and not self.problems


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def quick_fix(text: str, brief: Brief) -> str:
    """Fixes that need no AI: remove emojis / hashtags where they are not wanted."""
    ct = get_copy_type(brief.copy_type)
    fixed = text
    if ct.key == "script" or (
        ct.key == "caption" and not brief.toggles.get("emojis", ct.toggles["emojis"].default)
    ):
        fixed = EMOJI_RE.sub("", fixed)
    if ct.key == "caption" and not brief.toggles.get("hashtags", ct.toggles["hashtags"].default):
        fixed = HASHTAG_RE.sub("", fixed)
    return _tidy(fixed) if fixed != text else text


def auto_fix_many(brief: Brief, texts: list, generate_fn: Callable[[str, str], str],
                  max_attempts: int = 1, relax: str = "", keep: str = "") -> list:
    """Fix several versions with at most `max_attempts` AI requests in total.

    generate_fn(system, user) -> model text. `relax` and `keep` are for versions the user
    deliberately changed ("shorter"; the instruction to preserve). Each version ends up as
    the best one seen (fewest problems), so a bad attempt can never make a result worse."""
    n = len(texts)
    originals = [run_checks(t, brief, relax) for t in texts]
    current = [quick_fix(t, brief) for t in texts]
    problems = [run_checks(t, brief, relax) for t in current]
    best_text, best_problems = list(current), list(problems)
    tries = [0] * n
    rounds, error = 0, ""

    while rounds < max_attempts:
        failing = [i for i in range(n) if problems[i]]
        if not failing:
            break
        system, user = build_batch_fix_prompt(
            brief, [(current[i], problems[i]) for i in failing], keep=keep)
        try:
            output = generate_fn(system, user)
        except LLMError as e:
            error = str(e)
            break
        rounds += 1
        for i in failing:
            tries[i] += 1
        revised = parse_versions(output)
        if len(revised) != len(failing):   # can't safely match answers to versions
            break
        for i, text in zip(failing, revised):
            current[i] = quick_fix(text, brief)
            problems[i] = run_checks(current[i], brief, relax)
            if len(problems[i]) < len(best_problems[i]):
                best_text[i], best_problems[i] = current[i], problems[i]

    return [AutoFixResult(best_text[i], tries[i], best_problems[i], originals[i], error)
            for i in range(n)]


def auto_fix(brief: Brief, text: str, generate_fn: Callable[[str, str], str],
             max_attempts: int = 1, relax: str = "", keep: str = "") -> AutoFixResult:
    """Single-version convenience wrapper."""
    return auto_fix_many(brief, [text], generate_fn, max_attempts, relax, keep)[0]
