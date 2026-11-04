"""Script Writer AI - a small Streamlit app that writes short video scripts."""
from __future__ import annotations

import csv
import hmac
import io
import os
import requests
from datetime import datetime
from pathlib import Path

import streamlit as st

from llm import DEFAULT_MODEL, LLMError, generate
from prompt import (
    LANGUAGES, LENGTHS, PLATFORMS, TONES, Brief, build_prompt, parse_versions, word_count,
)

BASE_DIR = Path(__file__).parent
FEEDBACK_FILE = BASE_DIR / "feedback" / "feedback.csv"
FEEDBACK_COLUMNS = [
    "time", "product", "audience", "qualities", "offer", "language", "length",
    "tone", "script", "rating", "whats_weak", "expert_rewrite",
]


# ---------- config helpers ----------
def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Minimal .env loader so no extra package is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_setting(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file locally is normal
        pass
    return os.environ.get(name, default)


def save_feedback(row: dict) -> None:
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not FEEDBACK_FILE.exists()
    with FEEDBACK_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FEEDBACK_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in FEEDBACK_COLUMNS})

def notify_developer(row: dict) -> bool:
    """Send a saved review to Discord. Never raises, so saving can't break."""
    url = get_setting("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    text = (
        f"📝 New review: {row.get('rating')}/5\n"
        f"{row.get('product')} | {row.get('language')} | {row.get('length')} | {row.get('tone')}\n\n"
        f"SCRIPT:\n{row.get('script')}\n\n"
        f"WEAK: {row.get('whats_weak') or '-'}\n\n"
        f"HER REWRITE: {row.get('expert_rewrite') or '-'}"
    ).replace("@", "@\u200b")  # stops @everyone pings from user text
    try:
        if len(text) <= 1900:
            r = requests.post(url, json={"content": text}, timeout=15)
        else:  # Discord limit is 2000 chars, so attach the full text as a file
            r = requests.post(url, data={"content": text[:1900] + "…"},
                              files={"file": ("review.txt", text.encode("utf-8"))}, timeout=15)
        return r.status_code < 300
    except requests.RequestException:
        return False

def feedback_csv_bytes() -> bytes | None:
    if not FEEDBACK_FILE.exists():
        return None
    return FEEDBACK_FILE.read_bytes()


# ---------- app ----------
load_dotenv()
st.set_page_config(page_title="Script Writer AI", page_icon="🎬", layout="centered")


def password_gate() -> None:
    password = get_setting("APP_PASSWORD")
    if not password or st.session_state.get("authed"):
        return
    st.title("🎬 Script Writer AI")
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered, password):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


password_gate()

st.title("🎬 Script Writer AI")
st.caption("Short video scripts: hook question → what it offers → offer & call to action.")

with st.sidebar:
    st.header("Settings")
    model = st.text_input("AI model", value=get_setting("GEMINI_MODEL", DEFAULT_MODEL),
                          help="If you see a 'model not found' error, try gemini-flash-latest")
    creativity = st.slider("Creativity", 0.2, 1.2, 0.9, 0.1)
    n_versions = st.radio("Versions per request", [1, 2, 3], index=2, horizontal=True)
    st.info("Free AI limits are small. If you hit a limit, wait a bit and retry. "
            "Don't enter confidential client details.")

with st.form("brief"):
    product = st.text_input("What are you selling?*", placeholder="e.g. Cotton summer kurta for men")
    audience = st.text_input("Who is it for?*", placeholder="e.g. Young men, 18-30, Pakistan")
    qualities = st.text_area("2-3 main qualities* (one per line)",
                             placeholder="Soft breathable cotton\nDoes not shrink\nSizes S to XXL")
    offer = st.text_input("Offer or discount (optional)", placeholder="e.g. Free delivery this week")
    c1, c2 = st.columns(2)
    language = c1.selectbox("Language", list(LANGUAGES))
    length = c2.selectbox("Length", list(LENGTHS), index=1)
    c3, c4 = st.columns(2)
    tone = c3.selectbox("Tone", TONES)
    platform = c4.selectbox("Platform", PLATFORMS)
    with st.expander("More options"):
        avoid = st.text_input("Words or claims to avoid")
        extra = st.text_area("Anything else the AI should know?")
    submitted = st.form_submit_button("Write my script", type="primary", use_container_width=True)

if submitted:
    brief = Brief(
        product=product, audience=audience, qualities=qualities.splitlines(), offer=offer,
        language=language, length=length, tone=tone, platform=platform,
        avoid=avoid, extra=extra, versions=n_versions,
    )
    missing = brief.missing()
    if missing:
        st.warning("Please fill in: " + ", ".join(missing))
    else:
        system, user = build_prompt(brief)
        try:
            with st.spinner("Writing..."):
                text = generate(system, user, get_setting("GEMINI_API_KEY"),
                                model=model, temperature=creativity)
            st.session_state["result"] = {"brief": brief, "versions": parse_versions(text)}
        except LLMError as e:
            st.session_state.pop("result", None)
            st.error(str(e))

result = st.session_state.get("result")
if result:
    brief: Brief = result["brief"]
    st.subheader("Your scripts")
    for i, script in enumerate(result["versions"], start=1):
        st.markdown(f"**Version {i}**  ·  {word_count(script)} words")
        st.code(script, language=None, wrap_lines=True)  # copy button built in
        with st.expander(f"Review version {i}"):
            with st.form(f"fb_{i}"):
                rating = st.slider("How good is it?", 1, 5, 3)
                weak = st.text_area("What's weak or wrong?")
                rewrite = st.text_area("How would you write it? (optional - very valuable)")
                if st.form_submit_button("Save review"):
                    row = {
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "product": brief.product, "audience": brief.audience,
                        "qualities": " | ".join(brief.qualities_clean), "offer": brief.offer,
                        "language": brief.language, "length": brief.length, "tone": brief.tone,
                        "script": script, "rating": rating, "whats_weak": weak,
                        "expert_rewrite": rewrite,
                    }
                    save_feedback(row)
                    sent = notify_developer(row)
                    st.success("Saved and sent. Thank you!" if sent else "Saved. Thank you!")

# data = feedback_csv_bytes()
# if data:
#     st.divider()
#     st.download_button("⬇️ Download all reviews (CSV)", data, "feedback.csv", "text/csv")
#     st.caption("Tip: on the free hosted version, saved reviews can disappear when the app "
#                "restarts, so download them regularly and send the file to the developer.")
