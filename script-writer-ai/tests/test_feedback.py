import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback import FEEDBACK_COLUMNS, feedback_csv_bytes, notify_developer, save_feedback


def row(**kw):
    base = {"copy_type": "Video script", "product": "Bottle", "script": "Hi?", "rating": 4,
            "whats_weak": "", "expert_rewrite": "My version"}
    base.update(kw)
    return base


def test_save_creates_file_with_header(tmp_path):
    p = tmp_path / "fb" / "feedback.csv"
    save_feedback(row(), p)
    save_feedback(row(product="Cake"), p)
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    assert [r["product"] for r in rows] == ["Bottle", "Cake"]
    assert feedback_csv_bytes(p) is not None
    assert feedback_csv_bytes(tmp_path / "missing.csv") is None


def test_old_format_file_is_kept_not_corrupted(tmp_path):
    p = tmp_path / "feedback.csv"
    p.write_text("time,product\n2026-01-01,Old\n", encoding="utf-8-sig")
    save_feedback(row(), p)
    assert list(csv.reader(p.open(encoding="utf-8-sig")))[0] == FEEDBACK_COLUMNS
    assert len(list(tmp_path.glob("feedback_old_*.csv"))) == 1


class FakePost:
    def __init__(self, status=204):
        self.status, self.calls = status, []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))

        class R:
            status_code = self.status
        return R()


def test_notify_without_url_does_nothing():
    assert notify_developer(row(), "") is False


def test_notify_sends_and_blocks_mentions(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr("feedback.requests.post", fake)
    assert notify_developer(row(script="hello @everyone"), "https://hook") is True
    content = fake.calls[0][1]["json"]["content"]
    assert "@everyone" not in content and "Video script" in content


def test_notify_long_text_is_sent_as_file(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr("feedback.requests.post", fake)
    notify_developer(row(script="x" * 3000), "https://hook")
    assert "files" in fake.calls[0][1]


def test_notify_failure_never_raises(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr("feedback.requests.post", boom)
    assert notify_developer(row(), "https://hook") is False
    monkeypatch.setattr("feedback.requests.post", FakePost(500))
    assert notify_developer(row(), "https://hook") is False


def test_discord_message_shows_version_note(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr("feedback.requests.post", fake)
    notify_developer(row(version_note="Refined from version 1 (Make it shorter)"), "https://hook")
    assert "Refined from version 1" in fake.calls[0][1]["json"]["content"]



# ---------------------------------------------------------------------------
# Discord log of everything the tool does
# ---------------------------------------------------------------------------
from feedback import (DISCORD_LIMIT, block_messages, brief_lines, chunk_text, followup_messages,
                      generation_messages, post_discord, post_discord_async)
from prompt import Brief


def a_brief(**kw):
    base = dict(product="Cotton kurta", audience="Young men", qualities=["Soft cotton", "Sizes S to XXL"],
                pain_points=["Sticky shirts"], offer="Free delivery", language="Roman Urdu",
                length="30 seconds", tone="Friendly", platform="Instagram Reels", avoid="cheap",
                extra="Available in navy", copy_type="script", format="Shot-by-shot (timestamps)",
                shots="market walk", cta="Order today")
    base.update(kw)
    return Brief(**base)


def test_chunk_text_respects_the_limit_and_loses_nothing():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(100))
    chunks = chunk_text(text, 500)
    assert all(len(c) <= 500 for c in chunks) and "\n".join(chunks) == text
    long_line = "y" * 1200
    assert [len(c) for c in chunk_text(long_line, 500)] == [500, 500, 200]


def test_block_messages_fit_discord_and_each_has_closed_code_fences():
    msgs = block_messages("**Header**", "word " * 1500, "footer text")
    assert len(msgs) > 1 and all(len(m) <= 2000 for m in msgs)
    assert all(m.count("```") == 2 for m in msgs)
    assert msgs[0].startswith("**Header**") and "(part 2 of" in msgs[1] and msgs[-1].endswith("footer text")


def test_user_text_cannot_break_the_block_or_ping_everyone():
    msgs = block_messages("h", "hello @everyone ``` oops", "")
    assert "@everyone" not in msgs[0] and msgs[0].count("```") == 2


def test_brief_lines_show_every_field_for_a_shot_list():
    text = "\n".join(brief_lines(a_brief()))
    for needle in ("Shot-by-shot (timestamps)", "Product: Cotton kurta", "Audience: Young men", "- Soft cotton",
                   "- Sizes S to XXL", "- Sticky shirts", "Offer: Free delivery", "Call to action: Order today",
                   "Language: Roman Urdu", "Length: 30 seconds", "Tone: Friendly", "Platform: Instagram Reels",
                   "Shots they can film: market walk", "cheap", "Available in navy"):
        assert needle in text, needle


def test_brief_lines_only_show_fields_that_exist_for_the_type_and_mark_empty_ones():
    caption = "\n".join(brief_lines(a_brief(copy_type="caption", format="", shots="", cta="", pain_points=[],
                                             offer="", toggles={"hashtags": False})))
    assert "Add hashtags: no" in caption and "Use emojis: yes" in caption
    assert "Shots they can film" not in caption and "Format:" not in caption
    assert "Offer: -" in caption and "Problems it solves:\n  -" in caption
    product = "\n".join(brief_lines(a_brief(copy_type="product", format="", keywords="kurta")))
    assert "Keywords: kurta" in product and "Call to action" not in product


def test_generation_messages_contain_the_brief_and_every_version_with_its_checks():
    versions = [{"text": "Version one text?", "note": "Auto-fixed", "problems": []},
                {"text": "Version two text?", "note": "", "problems": ["Offer missing."]}]
    msgs = generation_messages("a1b2c3", a_brief(), versions, "Settings: 3 version(s)", 4)
    joined = "\n".join(msgs)
    assert msgs[0].startswith("\U0001F195 **#a1b2c3**") and "AI request #4" in msgs[0]
    assert "Product: Cotton kurta" in msgs[0] and "Settings: 3 version(s)" in msgs[0]
    assert "Version one text?" in joined and "Version two text?" in joined
    assert "Auto-fixed" in joined and "Passed all automatic checks" in joined and "Offer missing." in joined
    assert all(len(m) <= 2000 for m in msgs)


def test_a_long_shot_list_is_split_over_several_messages_without_losing_text():
    long_text = "\n".join(f"VISUAL: scene {i} " + "z" * 80 for i in range(60))
    msgs = generation_messages("a1b2c3", a_brief(), [{"text": long_text, "note": "", "problems": []}])
    assert all(len(m) <= 2000 for m in msgs)
    assert all(f"scene {i} " in "\n".join(msgs) for i in range(60))


def test_followup_messages_say_what_changed_and_include_the_text():
    item = {"text": "Shorter text", "note": "Refined from version 1 (Make it shorter)", "problems": []}
    msgs = followup_messages("a1b2c3", a_brief(), item, 7)
    assert "Refined from version 1 (Make it shorter)" in msgs[0] and "Cotton kurta" in msgs[0]
    assert "Shorter text" in msgs[0] and "AI request #7" in msgs[0]


def test_post_discord_sends_every_message_in_order_and_survives_a_rate_limit(monkeypatch):
    monkeypatch.setattr("feedback.time.sleep", lambda s: None)
    calls = []

    class R:
        def __init__(self, status, body=None):
            self.status_code, self._body = status, body or {}

        def json(self):
            return self._body

    answers = [R(204), R(429, {"retry_after": 0.1}), R(204), R(204)]

    def fake_post(url, json=None, timeout=None):
        calls.append(json["content"])
        return answers.pop(0)

    monkeypatch.setattr("feedback.requests.post", fake_post)
    assert post_discord("https://hook", ["one", "two", "three"]) is True
    assert calls == ["one", "two", "two", "three"]          # "two" was retried once


def test_post_discord_never_raises_and_needs_a_url(monkeypatch):
    import requests
    monkeypatch.setattr("feedback.time.sleep", lambda s: None)

    def boom(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr("feedback.requests.post", boom)
    assert post_discord("https://hook", ["x"]) is False
    assert post_discord("", ["x"]) is False
    assert post_discord_async("", ["x"]) is None and post_discord_async("https://hook", []) is None


def test_post_discord_async_runs_in_the_background(monkeypatch):
    monkeypatch.setattr("feedback.time.sleep", lambda s: None)
    sent = []

    class R:
        status_code = 204

    monkeypatch.setattr("feedback.requests.post", lambda url, json=None, timeout=None: sent.append(json) or R())
    thread = post_discord_async("https://hook", ["a", "b"])
    thread.join(timeout=5)
    assert [m["content"] for m in sent] == ["a", "b"]


def a_shot_list(segments=7):
    return "\n\n".join(
        f"{i * 9}-{(i + 1) * 9}s\nVISUAL: " + "scene " * 20 + "\nVOICEOVER: " + "words " * 20 + "\nON-SCREEN TEXT: TEXT"
        for i in range(segments))


def test_a_long_shot_list_is_only_ever_split_between_segments():
    import re
    text = a_shot_list(9)
    chunks = chunk_text(text, 900)
    assert len(chunks) > 1 and all(len(c) <= 900 for c in chunks)
    assert "\n\n".join(chunks) == text
    assert all(re.match(r"\d+-\d+s\n", c) for c in chunks)       # each chunk starts at a segment


def test_split_log_messages_start_with_a_timestamp_and_name_what_they_continue():
    import re
    msgs = generation_messages("a1b2c3", a_brief(), [{"text": a_shot_list(9), "note": "", "problems": []}])
    version_msgs = [m for m in msgs if "Version 1" in m.split("\n")[0] or m.startswith("(part")]
    continued = [m for m in version_msgs if m.startswith("(part")]
    assert continued and all("a1b2c3" in m.split("\n")[0] and "Version 1" in m.split("\n")[0] for m in continued)
    for m in version_msgs:
        first_line_of_code = m.split("```\n")[1].split("\n")[0]
        assert re.match(r"\d+-\d+s$", first_line_of_code), first_line_of_code
    assert all(len(m) <= 2000 for m in msgs)


def test_chunking_still_handles_text_without_blank_lines_or_with_one_huge_paragraph():
    lines = "\n".join(f"line {i} " + "x" * 50 for i in range(100))
    chunks = chunk_text(lines, 500)
    assert all(len(c) <= 500 for c in chunks) and "\n".join(chunks) == lines
    assert [len(c) for c in chunk_text("y" * 1200, 500)] == [500, 500, 200]
