import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks import (copied_phrases, missing_qualities, normalize_numbers, run_checks,
                    shot_list_problems, spoken_text, unsupported_claims)
from prompt import Brief, load_examples


def brief(**kw):
    base = dict(product="Steel bottle", audience="Students",
                qualities=["Keeps cold for 24 hours", "Leak-proof"], offer="Free delivery",
                length="15 seconds", copy_type="script", platform="Instagram Reels")
    base.update(kw)
    return Brief(**base)


GOOD_SCRIPT = ("Why settle for warm water? This steel bottle keeps drinks cold for 24 hours and the "
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
                   copy_type=e.get("type", "script"), format=e.get("format", ""),
                   pain_points=b.get("pain_points", []), shots=b.get("shots", ""),
                   cta=b.get("cta", ""))
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
    text = ("Why settle for dead earbuds mid-workout? " + "word " * 55 +
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


FAN = dict(product="Handheld fan", audience="Travellers", offer="", length="30 seconds",
           qualities=["43,000 RPM motor", "9,000 mAh battery", "Built-in flashlight and power bank"])


def fan_text(body):
    return "Dreading the heat? " + body + " " + "word " * 40


def test_quality_split_across_versions_is_caught():
    only_one = fan_text("This fan spins at 43,000 RPM so you stay cool all day long.")
    problems = run_checks(only_one, brief(**FAN))
    assert has(problems, "key qualities may be missing")
    assert has(problems, "9,000 mAh battery") and has(problems, "flashlight")
    assert not has(problems, "43,000 RPM")


def test_all_qualities_present_passes_even_when_worded_differently():
    allq = fan_text("A 43000 RPM motor, a big 9,000 mAh battery, plus a flashlight that works as a power bank.")
    assert not has(run_checks(allq, brief(**FAN)), "may be missing")


def test_thousands_separator_does_not_cause_false_number_alarms():
    assert not has(run_checks(fan_text("It has 43000 RPM, 9000 mAh, a flashlight and a power bank."),
                              brief(**FAN)), "numbers")
    assert not has(run_checks(fan_text("It has 43,000 RPM, 9,000 mAh, a flashlight and a power bank."),
                              brief(**FAN)), "numbers")


def test_text_only_quality_needs_half_its_words():
    b = brief(qualities=["Leak-proof lid", "Sweat-resistant"], offer="")
    assert missing_qualities("The lid never leaks and is sweat resistant.", b) == []
    assert missing_qualities("Cold all day, with free delivery.", b) == ["Leak-proof lid", "Sweat-resistant"]


def test_translated_copy_only_checks_numbers():
    b = brief(language="Roman Urdu", qualities=["Leak-proof lid", "24 hours cold"], offer="")
    assert missing_qualities("Ye bottle 24 ghante thanda rakhti hai", b) == []
    assert missing_qualities("Ye bottle band rehti hai, leak nahi hoti", b) == ["24 hours cold"]


def test_short_captions_and_google_ads_skip_the_coverage_check():
    cap = brief(copy_type="caption", length="Short", platform="Instagram", offer="", **{})
    assert not has(run_checks("Cool bottle", cap), "key qualities")
    g = brief(copy_type="ad", platform="Google search ad", offer="")
    assert not has(run_checks("HEADLINE 1: Cold bottle", g), "key qualities")


# ---------------------------------------------------------------------------
# Feedback from a professional copywriter (ApexHydro bottle brief)
# ---------------------------------------------------------------------------
APEX = dict(
    product="ApexHydro Pro 32oz (1 Liter) Insulated Sports Bottle",
    audience="Gym-goers, runners and outdoor athletes, 18-35",
    qualities=["24-Hour Ice Lock: double-wall vacuum-insulated stainless steel keeps water ice-cold in 40C heat",
               "Zero-Leak Locking Lid: throw it upside down in a gym bag with zero spills",
               "One-Handed Magnetic Chug Cap: flips open with one thumb mid-set and snaps back magnetically",
               "Impact-Resistant Silicone Base: doesn't dent or clang loudly when dropped"],
    pain_points=["Water turning lukewarm 20 minutes into a workout", "Cheap bottles leaking"],
    offer="15% off + free shipping", extra="Price: $34", length="30 seconds",
    copy_type="script", platform="Instagram Reels",
)

TOOL_OUTPUT_1 = ("Tired of lukewarm water ruining your workout? The ApexHydro Pro 32oz uses double-wall vacuum "
                 "insulation to keep water ice-cold for 24 hours. Toss it upside down in your gym bag; the zero-leak "
                 "locking lid prevents spills. Mid-set, flip the magnetic chug cap open with one thumb for a fast "
                 "drink. Plus, the impact-resistant silicone base stops loud clangs when dropped. Get yours for $34 "
                 "with 15 percent off and free shipping. Tap the link in bio to grab yours!")
TOOL_OUTPUT_2 = ("Sick of cheap bottles leaking all over your gym bag? Upgrade to the ApexHydro Pro 32oz. Double-wall "
                 "vacuum-insulated stainless steel locks in ice-cold water for 24 hours straight. Throw it right into "
                 "your bag because the zero-leak locking lid is completely secure. When you need a fast drink, the "
                 "magnetic chug cap flips open with one hand. The impact-resistant silicone base prevents loud dings. "
                 "Get it for $34 with 15 percent off and free shipping. Tap the link in bio!")
TOOL_OUTPUT_3 = ("Why drink warm water during your heavy session? The ApexHydro Pro 32oz keeps your drink ice-cold for "
                 "24 hours with double-wall vacuum insulation. Toss it carelessly into your gym bag; the zero-leak "
                 "locking lid ensures your gear stays dry. Between sets, pop the magnetic chug cap open with a single "
                 "thumb for instant hydration. Even if you drop it, the impact-resistant silicone base absorbs the "
                 "impact silently. Grab yours for $34 with 15 percent off and free shipping. Tap the link in bio!")


def test_the_professionals_three_outputs_are_now_caught():
    b = brief(**APEX)
    for text in (TOOL_OUTPUT_1, TOOL_OUTPUT_2, TOOL_OUTPUT_3):
        problems = run_checks(text, b)
        assert has(problems, "price is read out loud"), problems
    assert has(run_checks(TOOL_OUTPUT_1, b), "cliché")       # "Tired of ..."
    assert has(run_checks(TOOL_OUTPUT_2, b), "cliché")       # "Sick of ..."
    assert not has(run_checks(TOOL_OUTPUT_3, b), "cliché")
    assert has(run_checks(TOOL_OUTPUT_2, b), "straight from your spec lines")  # lifted spec wording


def test_cliche_openers_are_only_checked_for_english():
    text = "Tired of this? " + "word " * 70
    assert has(run_checks(text, brief(offer="", length="30 seconds")), "cliché")
    assert not has(run_checks(text, brief(offer="", length="30 seconds", language="Roman Urdu")), "cliché")


def test_reworded_quality_is_not_flagged_as_missing():
    b = brief(qualities=["Zero-Leak Locking Lid", "Impact-Resistant Silicone Base"], offer="")
    text = "Why settle? The lid never leaks in your bag and the base shrugs off drops. " + "word " * 15
    assert missing_qualities(text, b) == []


def test_spoken_price_is_allowed_when_the_buyer_put_it_in_the_offer():
    text = "Why settle for less? " + "word " * 35 + "Get it for $34 today."
    assert has(run_checks(text, brief(offer="", length="15 seconds")), "price is read out loud")
    assert not has(run_checks(text, brief(offer="Only $34 today", length="15 seconds")), "price is read out")


def test_copied_phrases_ignore_numbers_and_short_overlaps():
    b = brief(qualities=["Keeps cold for 24 hours", "Zero-leak locking lid"])
    assert copied_phrases("It keeps drinks cold for 24 hours.", b) == []
    assert copied_phrases("The zero leak locking lid is secure.", b) == ["zero leak locking lid"]


# ---------- shot-by-shot ----------
SHOT = dict(format="Shot-by-shot (timestamps)", length="30 seconds", offer="15% off",
            qualities=["Keeps drinks cold for 24 hours", "Never leaks in a bag"], copy_type="script",
            platform="Instagram Reels")
VALID_SHOT_LIST = """0-3s
VISUAL: Runner shakes the open bottle upside down over a gym bag.
VOICEOVER: If your bottle can't survive this, bin it.
ON-SCREEN TEXT: TEST YOUR BOTTLE

3-10s
VISUAL: Ice cubes clink inside the bottle after a long day in the sun.
VOICEOVER: Still ice cold after twenty-four hours, even in a heatwave, and nothing leaks into your bag.
ON-SCREEN TEXT: 24 HOURS COLD

10-20s
VISUAL: Close-up of the cap flipping open with one thumb.
VOICEOVER: One thumb opens it mid-set, and the cap stays out of your face while you drink. No stopping, no fiddling, no wasted rest time between sets.
ON-SCREEN TEXT: ONE-HAND CAP

20-30s
VISUAL: Athlete walks out of the gym with the bottle, product shot.
VOICEOVER: Grab yours while the launch batch lasts. Tap the link in bio for 15% off before it sells out.
ON-SCREEN TEXT: 15% OFF"""


def test_valid_shot_list_passes():
    b = brief(**SHOT)
    assert run_checks(VALID_SHOT_LIST, b) == []
    assert shot_list_problems(VALID_SHOT_LIST, b) == []


def test_shot_list_hook_does_not_have_to_be_a_question_and_timestamps_are_not_numbers_to_verify():
    problems = run_checks(VALID_SHOT_LIST, brief(**SHOT))
    assert not has(problems, "isn't a question") and not has(problems, "numbers")


def test_word_count_for_shot_lists_uses_the_voiceover_only():
    b = brief(**SHOT)
    words = len(spoken_text(VALID_SHOT_LIST, b).split())
    assert 59 <= words <= 98 and len(VALID_SHOT_LIST.split()) > words


def test_shot_list_structure_problems():
    b = brief(**SHOT)
    assert has(shot_list_problems("Just a paragraph of voiceover.", b), "isn't a timestamped shot list")
    assert has(shot_list_problems(VALID_SHOT_LIST.replace("3-10s", "5-10s"), b), "gap or overlap")
    assert has(shot_list_problems(VALID_SHOT_LIST.replace("20-30s", "20-24s"), b), "ends at 24s")
    assert has(shot_list_problems(VALID_SHOT_LIST.replace("0-3s", "0-7s").replace("3-10s", "7-10s"), b),
               "hook segment runs 7s")
    broken = VALID_SHOT_LIST.replace("VOICEOVER: One thumb", "NOTE: One thumb")
    assert has(shot_list_problems(broken, b), "missing a VISUAL or VOICEOVER")


def test_a_cliche_hook_is_caught_in_the_first_voiceover_line_of_a_shot_list():
    cliche = VALID_SHOT_LIST.replace("If your bottle can't survive this, bin it.", "Tired of warm water? Bin it.")
    assert has(run_checks(cliche, brief(**SHOT)), "cliché")


# ---------------------------------------------------------------------------
# Unsupported claims and AI tells (found while testing a headset and an achar brief)
# ---------------------------------------------------------------------------
HEADSET = dict(
    product="Wireless gaming headset", audience="Competitive gamers, 18-28",
    qualities=["7.1 surround sound", "40-hour battery", "Detachable mic with noise filter"],
    offer="20% off + free shipping this week", cta="Tap the link in bio before the offer ends",
    copy_type="script", format="Shot-by-shot (timestamps)", length="30 seconds", platform="TikTok",
)
ACHAR = dict(
    product="Ghar ka bana achar, glass jar mein", audience="Pakistani families",
    qualities=["Chhote batches mein ghar par bana hua", "Koi artificial rang ya preservative nahi",
               "Aam, lemon aur mixed flavours"],
    offer="", language="Roman Urdu", length="60 seconds", copy_type="script",
    format="Voiceover only", platform="General video",
)


def test_a_battery_spec_turned_into_a_week_is_flagged():
    b = brief(**HEADSET)
    text = ("0-3s\nVISUAL: Gamer slams the desk.\nVOICEOVER: Dead again?\nON-SCREEN TEXT: DEAD?\n\n"
            "3-30s\nVISUAL: Timer on the desk.\nVOICEOVER: Go a full week of heavy gaming before you charge. "
            "Tap the link in bio before the offer ends.\nON-SCREEN TEXT: 40-HOUR BATTERY")
    assert unsupported_claims(text, b) == ["full week"]
    assert has(run_checks(text, b), "claims your brief doesn't support")


def test_this_week_and_launch_week_are_not_claims():
    b = brief(**HEADSET)
    assert unsupported_claims("Free shipping this week only. Launch week deal.", b) == []


def test_a_time_span_is_fine_when_the_buyer_said_it():
    b = brief(qualities=["Battery lasts a whole week"], offer="")
    assert unsupported_claims("The battery lasts a whole week.", b) == []
    assert unsupported_claims("Lifetime warranty included.", brief(qualities=["Lifetime warranty"])) == []


def test_invented_origin_and_health_claims_are_flagged_in_roman_urdu_too():
    b = brief(**ACHAR)
    text = ("Dadi ke hath ke zaiqe ki talash hai? Khalis aur sehatmand khana. " + "word " * 120)
    assert sorted(unsupported_claims(text, b)) == ["dadi", "sehatmand"]
    assert unsupported_claims("Ghar ka bana achar, chhote batches mein.", b) == []


def test_visuals_are_not_checked_for_claims():
    b = brief(**HEADSET)
    text = "0-3s\nVISUAL: Time-lapse over a whole week of gaming.\nVOICEOVER: Dead again?\nON-SCREEN TEXT: DEAD?"
    assert unsupported_claims(text, b) == []


def test_em_dash_is_flagged_but_timestamp_dashes_are_not():
    assert has(run_checks("Why settle? Cold\u2014all day.", brief(offer="")), "em dash")
    shot = "0\u20143s\nVISUAL: x\nVOICEOVER: Why settle?\nON-SCREEN TEXT: y"
    assert not has(run_checks(shot, brief(**HEADSET)), "em dash")
    assert not has(run_checks("Why settle? Cold, all day.", brief(offer="")), "em dash")


def test_the_two_real_test_outputs_are_now_caught():
    achar_text = ("Dadi ke hath ke us purane zaiqe ki talash hai?\n\nIs mein kisi bhi tarah ke chemical ya "
                  "banawati rang ka istemal nahi hota, taake aap apni family ko khalis aur sehatmand khana "
                  "khila saken. Ras bhare aam, raseele lemon aur mazedaar mixed\u2014teeno lazeez zaiqe "
                  "mojood hain. " + "word " * 100)
    problems = run_checks(achar_text, brief(**ACHAR))
    assert has(problems, "'sehatmand'") and has(problems, "'dadi'") and has(problems, "em dash")
