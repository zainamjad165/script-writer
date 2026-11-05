import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks import normalize_numbers, run_checks
from prompt import Brief, load_examples


def brief(**kw):
    base = dict(product="Steel bottle", audience="Students",
                qualities=["Keeps cold for 24 hours", "Leak-proof"], offer="Free delivery",
                length="15 seconds", copy_type="script", platform="Instagram Reels")
    base.update(kw)
    return Brief(**base)


GOOD_SCRIPT = ("Tired of warm water? This steel bottle keeps drinks cold for 24 hours and the "
               "lid never leaks, so your bag stays dry all day long. Get free delivery today. "
               "Tap the link and order now.")


def has(problems, needle):
    return any(needle in p for p in problems)


def test_good_script_passes():
    assert run_checks(GOOD_SCRIPT, brief()) == []


def test_every_starter_example_passes_its_own_checks():
    for e in load_examples():
        b = e["brief"]
        br = Brief(product=b["product"], audience=b["audience"], qualities=b["qualities"],
                   offer=b.get("offer", ""), language=e.get("language", "English"),
                   length=e.get("length", ""), platform=e.get("platform", ""),
                   copy_type=e.get("type", "script"))
        assert run_checks(e["script"], br) == [], (e.get("type"), e.get("length"))


def test_script_hook_must_be_a_question():
    assert has(run_checks(GOOD_SCRIPT.replace("warm water?", "warm water."), brief()), "isn't a question")


def test_urdu_question_mark_counts_as_a_question():
    text = "کیا آپ تھک گئے ہیں؟ " + "word " * 38
    assert not has(run_checks(text, brief(language="Urdu (اردو)", offer="")), "isn't a question")


def test_long_hook_is_flagged():
    long_hook = "Are you really still tired of all of the warm lukewarm water in your bag every single day? "
    assert has(run_checks(long_hook + "word " * 25, brief(offer="")), "opening question is")


def test_script_with_emoji_is_flagged():
    assert has(run_checks(GOOD_SCRIPT + " 🎉", brief()), "emojis")


def test_word_count_outside_target_is_flagged_and_tolerance_applies():
    assert has(run_checks("Short one? Free delivery.", brief()), "target is 35-45")
    just_over = "Why wait? " + "word " * 40 + "free delivery"   # ~44 words, inside target
    assert not has(run_checks(just_over, brief()), "target is")


def test_numbers_not_in_brief_are_flagged_but_brief_numbers_pass():
    assert has(run_checks(GOOD_SCRIPT.replace("24 hours", "48 hours"), brief()), "48")
    assert not has(run_checks(GOOD_SCRIPT, brief()), "numbers")


def test_missing_offer_is_flagged():
    b = brief(offer="15% off first order")
    assert has(run_checks(GOOD_SCRIPT, b), "seems to be missing")
    assert not has(run_checks(GOOD_SCRIPT + " Enjoy 15% off.", b), "seems to be missing")


def test_invented_offer_is_flagged_only_when_buyer_gave_none():
    assert has(run_checks(GOOD_SCRIPT, brief(offer="")), "'free'")
    assert not has(run_checks(GOOD_SCRIPT, brief(offer="", extra="free delivery is standard")), "'free'")


def test_avoid_words():
    assert has(run_checks(GOOD_SCRIPT, brief(avoid="leaks, cheap")), "leaks")
    assert not has(run_checks(GOOD_SCRIPT, brief(avoid="cheap")), "avoid")


def test_caption_toggles():
    cap = dict(copy_type="caption", length="Short", platform="Instagram", offer="")
    assert has(run_checks("Cool bottle 😎", brief(toggles={"hashtags": True}, **cap)), "none were added")
    assert has(run_checks("Cool bottle #bottle", brief(toggles={"hashtags": False}, **cap)), "switched off")
    assert has(run_checks("Cool bottle 😎", brief(toggles={"hashtags": False, "emojis": False}, **cap)), "Emojis")


def test_facebook_headline_and_google_limits():
    fb = brief(copy_type="ad", length="Short", platform="Facebook / Instagram ad", offer="")
    text = "HEADLINE: " + "x" * 41 + "\nPRIMARY TEXT: " + "word " * 24 + "\nCALL TO ACTION: Shop Now"
    assert has(run_checks(text, fb), "headline is 41")
    g = brief(copy_type="ad", platform="Google search ad", offer="")
    assert has(run_checks("HEADLINE 1: " + "x" * 31, g), "31 characters")
    # the 1 in "HEADLINE 1" is a label, not a made-up number
    assert not has(run_checks("HEADLINE 1: Fresh cakes\nHEADLINE 2: Baked daily", g), "numbers")


def test_product_title_and_bullets():
    pr = brief(copy_type="product", length="Short", platform="Own website", offer="",
               toggles={"bullets": True})
    text = "TITLE: " + "x" * 71 + "\nDESCRIPTION: " + "word " * 48
    problems = run_checks(text, pr)
    assert has(problems, "title is 71") and has(problems, "none were added")
    with_bullets = "TITLE: Bottle\nDESCRIPTION: " + "word " * 48 + "\n- cold\n- sealed"
    assert not has(run_checks(with_bullets, pr), "Bullet")  # bullets excluded from the word count


def test_spelled_out_numbers_are_understood():
    assert normalize_numbers("twenty percent, thirty-two, two hundred and fifty, twenty-one") == \
        "20%, 32, 250, 21"
    # a lone "one" is ordinary English, not a number
    assert normalize_numbers("one clear call to action, no one") == "one clear call to action, no one"


def test_offer_written_in_words_counts_as_present():
    earbuds = brief(offer="20% off this weekend", length="30 seconds",
                    qualities=["8 hours of playback, 32 hours with the case"])
    text = ("Tired of dead earbuds mid-workout? " + "word " * 55 +
            "eight hours of music, plus thirty-two more in the case. "
            "Get twenty percent off this weekend. Tap the link.")
    problems = run_checks(text, earbuds)
    assert not has(problems, "seems to be missing") and not has(problems, "numbers")


def test_spelled_out_number_not_in_brief_is_still_flagged():
    assert has(run_checks(GOOD_SCRIPT.replace("24 hours", "forty-eight hours"), brief()), "48")


def test_relax_lets_a_deliberately_shorter_or_longer_text_pass_the_length_check():
    short = "Why wait? Free delivery."
    assert has(run_checks(short, brief()), "target is")
    assert not has(run_checks(short, brief(), relax="shorter"), "target is")
    assert has(run_checks(short, brief(), relax="longer"), "target is")
    long = "Why wait? " + "word " * 80 + "free delivery"
    assert has(run_checks(long, brief()), "target is")
    assert not has(run_checks(long, brief(), relax="longer"), "target is")
    assert has(run_checks(long, brief(), relax="shorter"), "target is")
