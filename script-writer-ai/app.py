"""Copywriter AI - a small Streamlit app that writes short-form marketing copy."""
from __future__ import annotations

import hmac
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from feedback import feedback_csv_bytes, notify_developer, save_feedback
from autofix import auto_fix_many
from checks import run_checks
from llm import DEFAULT_FALLBACK_MODELS, DEFAULT_MODEL, LLMError, generate
from prompt import (
    COPY_TYPES, LANGUAGES, REFINE_ACTIONS, REFINE_RELAX, TONES, Brief, build_prompt, build_refine_prompt,
    get_copy_type, parse_versions, refine_instruction, word_count,
)

BASE_DIR = Path(__file__).parent
FEEDBACK_FILE = BASE_DIR / "feedback" / "feedback.csv"


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


# ---------- app ----------
load_dotenv()
st.set_page_config(page_title="Copywriter AI", page_icon="✍️", layout="centered")


def password_gate() -> None:
    password = get_setting("APP_PASSWORD")
    if not password or st.session_state.get("authed"):
        return
    st.title("✍️ Copywriter AI")
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered, password):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


password_gate()

st.title("✍️ Copywriter AI")
st.caption("Pick what you need, fill the short form, get ready-to-use copy.")

with st.sidebar:
    st.header("Settings")
    model = st.text_input("AI model", value=get_setting("GEMINI_MODEL", DEFAULT_MODEL),
                          help="If you see a 'model not found' error, try gemini-flash-latest")
    creativity = st.slider("Creativity", 0.2, 1.2, 0.9, 0.1)
    n_versions = st.radio("Versions per request", [1, 2, 3], index=2, horizontal=True)
    autofix_tries = st.radio(
        "Auto-fix problems", [0, 1, 2], index=1, horizontal=True, key="autofix_tries",
        format_func=lambda n: "Off" if n == 0 else f"{n} try" if n == 1 else f"{n} tries",
        help="When a result fails a check, the AI revises it automatically. "
             "Each try is ONE extra request that fixes all failing versions together. "
             "Emojis and hashtags are removed for free, without any request.")
    usage_box = st.empty()
    st.info("Free AI limits are small. If you hit a limit, wait a bit and retry. "
            "Don't enter confidential client details.")

FALLBACKS = [m.strip() for m in get_setting(
    "GEMINI_FALLBACK_MODELS", ",".join(DEFAULT_FALLBACK_MODELS)).split(",") if m.strip()]


def ai(system: str, user: str, temperature: float) -> str:
    """Every AI request goes through here, so the sidebar can count them."""
    st.session_state["ai_requests"] = st.session_state.get("ai_requests", 0) + 1
    return generate(system, user, get_setting("GEMINI_API_KEY"), model=model,
                    temperature=temperature, fallback_models=FALLBACKS)


def fix_fn(system: str, user: str) -> str:
    """Fixes should be careful, so use a lower creativity than the first draft."""
    return ai(system, user, min(creativity, 0.6))


def fix_note(fix) -> str:
    if fix.fixed:
        return "Auto-fixed"
    return f"Auto-fix tried {fix.attempts}x, some issues remain" if fix.attempts else ""


# The type picker sits outside the form so the form below can change with it.
type_by_label = {ct.label: key for key, ct in COPY_TYPES.items()}
chosen = st.selectbox("What do you want to write?", list(type_by_label), key="copy_type_label")
ct = get_copy_type(type_by_label[chosen])

with st.form("brief"):
    product = st.text_input("What are you selling?*", key="product",
                            placeholder="e.g. Cotton summer kurta for men")
    audience = st.text_input("Who is it for?*", key="audience",
                             placeholder="e.g. Young men, 18-30, Pakistan")
    qualities = st.text_area("2-3 main qualities* (one per line)", key="qualities",
                             placeholder="Soft breathable cotton\nDoes not shrink\nSizes S to XXL")
    offer = st.text_input("Offer or discount (optional)", key="offer",
                          placeholder="e.g. Free delivery this week")
    c1, c2 = st.columns(2)
    language = c1.selectbox("Language", list(LANGUAGES), key="language")
    lengths = list(ct.lengths)
    length = c2.selectbox(ct.length_label, lengths, index=lengths.index(ct.default_length),
                          key=f"{ct.key}_length")
    c3, c4 = st.columns(2)
    tone = c3.selectbox("Tone", TONES, key="tone")
    platform = c4.selectbox("Platform", ct.platforms, key=f"{ct.key}_platform")
    toggle_values = {}
    if ct.toggles:
        for col, (tkey, toggle) in zip(st.columns(len(ct.toggles)), ct.toggles.items()):
            toggle_values[tkey] = col.checkbox(toggle.label, value=toggle.default,
                                               key=f"{ct.key}_{tkey}")
    keywords = (st.text_input(ct.keywords_label, key=f"{ct.key}_keywords")
                if ct.keywords_label else "")
    with st.expander("More options"):
        avoid = st.text_input("Words or claims to avoid", key="avoid")
        extra = st.text_area("Anything else the AI should know?", key="extra")
    submitted = st.form_submit_button(f"Write my {ct.noun}", type="primary",
                                      use_container_width=True)

if submitted:
    brief = Brief(
        product=product, audience=audience, qualities=qualities.splitlines(), offer=offer,
        language=language, length=length, tone=tone, platform=platform, avoid=avoid,
        extra=extra, versions=n_versions, copy_type=ct.key, toggles=toggle_values,
        keywords=keywords,
    )
    missing = brief.missing()
    if missing:
        st.warning("Please fill in: " + ", ".join(missing))
    else:
        system, user = build_prompt(brief)
        try:
            with st.spinner("Writing..."):
                text = ai(system, user, creativity)
            drafts = parse_versions(text)
            fixes = [None] * len(drafts)
            if autofix_tries:
                with st.spinner("Checking and fixing..."):
                    fixes = auto_fix_many(brief, drafts, fix_fn, autofix_tries)
                if fixes and fixes[0].error:
                    st.warning(f"Auto-fix stopped early: {fixes[0].error}")
            versions = [
                {"text": f.text if f else d, "note": fix_note(f) if f else "", "relax": ""}
                for d, f in zip(drafts, fixes)
            ]
            st.session_state["result"] = {"brief": brief, "versions": versions}
        except LLMError as e:
            st.session_state.pop("result", None)
            st.error(str(e))

result = st.session_state.get("result")
if result:
    brief: Brief = result["brief"]
    result_type = get_copy_type(brief.copy_type)
    st.subheader(f"Your {result_type.noun}s")
    for idx, item in enumerate(list(result["versions"])):
        n = idx + 1
        copy = item["text"]
        note = f"  ·  {item['note']}" if item["note"] else ""
        st.markdown(f"**Version {n}**{note}  ·  {word_count(copy)} words · {len(copy)} characters")
        st.code(copy, language=None, wrap_lines=True)  # copy button built in

        relax = item.get("relax", "")
        problems = run_checks(copy, brief, relax)
        if problems:
            for problem in problems:
                st.warning(problem)
            if st.button("🔧 Fix these problems", key=f"fix_{idx}"):
                with st.spinner("Fixing..."):
                    fix = auto_fix_many(brief, [copy], fix_fn, 2, relax=relax)[0]
                if fix.error:
                    st.error(fix.error)
                elif fix.text == copy:
                    st.info("I couldn't improve this version. Try Refine → Custom change.")
                else:
                    tail = "" if fix.fixed else " (some issues remain)"
                    result["versions"].append(
                        {"text": fix.text, "note": f"Fixed from version {n}{tail}", "relax": relax})
                    st.rerun()
        else:
            st.caption("✅ Passed all automatic checks")

        with st.expander(f"Refine version {n}"):
            action = st.selectbox("What should change?", list(REFINE_ACTIONS), key=f"ra_{idx}")
            new_tone = custom = ""
            if action == "Change the tone":
                new_tone = st.selectbox("New tone", TONES, key=f"rt_{idx}")
            if action == "Custom change":
                custom = st.text_input("Describe the change", key=f"rc_{idx}",
                                       placeholder="e.g. mention the warranty in the last line")
            if st.button("Refine", key=f"refine_{idx}"):
                instruction = refine_instruction(action, new_tone, custom)
                if not instruction:
                    st.warning("Please describe the change first.")
                else:
                    system, user = build_refine_prompt(brief, copy, instruction)
                    try:
                        with st.spinner("Refining..."):
                            text = ai(system, user, creativity)
                        revised = parse_versions(text)
                        if revised:
                            label = new_tone and f"{action}: {new_tone}" or action
                            new_text = revised[0]
                            new_relax = REFINE_RELAX.get(action, "")
                            note = f"Refined from version {n} ({label})"
                            if autofix_tries:
                                with st.spinner("Checking..."):
                                    fix = auto_fix_many(brief, [new_text], fix_fn, autofix_tries,
                                                        relax=new_relax, keep=instruction)[0]
                                new_text = fix.text
                                if fix.fixed:
                                    note += ", auto-fixed"
                                elif fix.attempts:
                                    note += f", auto-fix tried {fix.attempts}x"
                            result["versions"].append(
                                {"text": new_text, "note": note, "relax": new_relax})
                            st.rerun()
                        else:
                            st.error("The AI returned nothing. Try again.")
                    except LLMError as e:
                        st.error(str(e))

        with st.expander(f"Review version {n}"):
            with st.form(f"fb_{idx}"):
                rating = st.slider("How good is it?", 1, 5, 3)
                weak = st.text_area("What's weak or wrong?")
                rewrite = st.text_area("How would you write it? (optional - very valuable)")
                if st.form_submit_button("Save review"):
                    row = {
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "copy_type": result_type.label, "platform": brief.platform,
                        "product": brief.product, "audience": brief.audience,
                        "qualities": " | ".join(brief.qualities_clean), "offer": brief.offer,
                        "language": brief.language, "length": brief.length, "tone": brief.tone,
                        "version_note": item["note"], "script": copy, "rating": rating,
                        "whats_weak": weak, "expert_rewrite": rewrite,
                    }
                    save_feedback(row, FEEDBACK_FILE)
                    sent = notify_developer(row, get_setting("DISCORD_WEBHOOK_URL"))
                    st.success("Saved and sent. Thank you!" if sent else "Saved. Thank you!")

# data = feedback_csv_bytes(FEEDBACK_FILE)
# if data:
#     st.divider()
#     st.download_button("⬇️ Download all reviews (CSV)", data, "feedback.csv", "text/csv")
#     st.caption("Tip: on the free hosted version, saved reviews can disappear when the app "
#                "restarts, so download them regularly and send the file to the developer.")

usage_box.caption(f"AI requests this session: {st.session_state.get('ai_requests', 0)}")
