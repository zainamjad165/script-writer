import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autofix import auto_fix, auto_fix_many, quick_fix
from llm import LLMError
from prompt import Brief, fix_instruction

BRIEF = Brief(product="Earbuds", audience="Gym-goers", qualities=["8 hours playback"],
              offer="20% off this weekend", length="15 seconds", copy_type="script",
              platform="Instagram Reels")

# 41 words, opens with a question, mentions the offer
GOOD = ("Battery dying mid-workout? These earbuds play for 8 hours without a charge, so your "
        "music never stops while you train. Grab 20% off this weekend only. Tap the link and "
        "order yours today before the weekend ends.")
# offer missing and an invented number
BAD = ("Battery dying mid-workout? These earbuds play for 8 hours and charge in 5 minutes, so "
       "your music never stops while you train. Tap the link and order yours today before "
       "the weekend ends and the stock runs out.")


class Gen:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, system, user):
        self.calls.append((system, user))
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_clean_text_makes_no_request():
    gen = Gen()
    res = auto_fix(BRIEF, GOOD, gen, max_attempts=2)
    assert res.text == GOOD and res.attempts == 0 and not gen.calls and not res.fixed


def test_problem_is_fixed_in_one_try():
    gen = Gen(GOOD)
    res = auto_fix(BRIEF, BAD, gen, max_attempts=2)
    assert res.fixed and res.text == GOOD and res.attempts == 1 and res.problems == []
    assert len(gen.calls) == 1                       # stops as soon as it passes
    system, user = gen.calls[0]
    assert "automatic check" in system and BAD in user and "PROBLEMS:" in user and "5" in user


def test_max_attempts_is_respected():
    gen = Gen(BAD, BAD, BAD)
    res = auto_fix(BRIEF, BAD, gen, max_attempts=2)
    assert res.attempts == 2 and len(gen.calls) == 2 and not res.fixed and res.problems


def test_off_means_no_requests():
    gen = Gen()
    res = auto_fix(BRIEF, BAD, gen, max_attempts=0)
    assert res.attempts == 0 and res.text == BAD and not gen.calls


def test_a_worse_attempt_never_replaces_the_original():
    worse = "No question here. Buy now at 99 dollars. " * 3
    res = auto_fix(BRIEF, BAD, Gen(worse), max_attempts=1)
    assert res.text == BAD


def test_rate_limit_stops_fixing_and_keeps_text():
    res = auto_fix(BRIEF, BAD, Gen(LLMError("Free limit reached")), max_attempts=2)
    assert res.text == BAD and res.attempts == 0 and "Free limit" in res.error


def test_empty_answer_stops_without_crashing():
    res = auto_fix(BRIEF, BAD, Gen("   "), max_attempts=2)
    assert res.text == BAD and res.attempts == 1


def test_fix_instruction_lists_every_problem():
    text = fix_instruction(["Problem A.", "Problem B."])
    assert "- Problem A." in text and "- Problem B." in text


# ---------- batching: one request fixes every failing version ----------
BAD2 = BAD.replace("5 minutes", "7 minutes")
GOOD2 = GOOD.replace("Battery dying mid-workout?", "Music cutting out mid-run?")
SEP = "\n===VERSION===\n"


def test_all_failing_versions_are_fixed_with_one_request():
    # versions: BAD (fails), a passing one, BAD2 (fails) -> only 2 go to the AI, in 1 request
    passing = GOOD.replace("Grab 20% off", "Get 20% off")
    gen = Gen(GOOD + SEP + GOOD2)
    results = auto_fix_many(BRIEF, [BAD, passing, BAD2], gen, max_attempts=1)
    assert len(gen.calls) == 1
    assert [r.text for r in results] == [GOOD, passing, GOOD2]
    assert [r.fixed for r in results] == [True, False, True]
    assert [r.attempts for r in results] == [1, 0, 1]
    user = gen.calls[0][1]
    assert user.count("VERSION ") == 2 and passing not in user      # the good one isn't sent


def test_wrong_number_of_answers_changes_nothing():
    gen = Gen(GOOD)                                   # asked to fix 2 versions, got 1 back
    results = auto_fix_many(BRIEF, [BAD, BAD2], gen, max_attempts=2)
    assert [r.text for r in results] == [BAD, BAD2] and len(gen.calls) == 1


# ---------- free fixes: no AI request ----------
def test_quick_fix_strips_emojis_from_scripts():
    assert quick_fix("Cold drinks? 😎 Order now 🎉", BRIEF) == "Cold drinks? Order now"


def test_quick_fix_respects_caption_toggles():
    cap = Brief(product="x", audience="y", qualities=["z"], copy_type="caption",
                toggles={"emojis": False, "hashtags": False})
    assert quick_fix("Nice 😎 bottle #cold #steel", cap) == "Nice bottle"
    keep = Brief(product="x", audience="y", qualities=["z"], copy_type="caption",
                 toggles={"emojis": True, "hashtags": True})
    assert quick_fix("Nice 😎 bottle #cold", keep) == "Nice 😎 bottle #cold"


def test_quick_fix_alone_can_solve_it_with_zero_requests():
    gen = Gen()
    text = GOOD + " 🎉"
    res = auto_fix(BRIEF, text, gen, max_attempts=2)
    assert res.text == GOOD
    assert res.fixed and res.attempts == 0 and not gen.calls


# ---------- after the user deliberately shortened / lengthened ----------
SHORT = "Battery dying mid-workout? These earbuds play 8 hours. Get 20% off this weekend."


def test_relax_shorter_ignores_a_short_result_but_not_other_problems():
    assert auto_fix(BRIEF, SHORT, Gen(), max_attempts=0).problems          # too short normally
    res = auto_fix(BRIEF, SHORT, Gen(), max_attempts=1, relax="shorter")
    assert res.problems == [] and res.attempts == 0
    invented = SHORT.replace("8 hours", "99 hours")
    assert auto_fix(BRIEF, invented, Gen("x"), max_attempts=0, relax="shorter").problems


def test_keep_instruction_is_passed_to_the_ai():
    gen = Gen(SHORT)
    bad_short = SHORT.replace("8 hours", "99 hours")
    auto_fix(BRIEF, bad_short, gen, max_attempts=1, relax="shorter", keep="Make it shorter")
    assert "Do not undo that change" in gen.calls[0][0] and "Make it shorter" in gen.calls[0][0]
