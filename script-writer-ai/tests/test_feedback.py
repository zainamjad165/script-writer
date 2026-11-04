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
