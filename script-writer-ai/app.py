"""Copywriter AI - a small Streamlit app that writes short-form marketing copy."""
from __future__ import annotations

import hmac
import os
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import streamlit as st

from feedback import (feedback_csv_bytes, followup_messages, generation_messages,
                      note_messages, notify_developer, post_discord_async, save_feedback)
from autofix import auto_fix_many
from checks import is_shot_list, rank_versions, run_checks, spoken_text
from llm import DEFAULT_FALLBACK_MODELS, DEFAULT_MODEL, LLMError, generate
from prompt import (
    COPY_TYPES, LANGUAGES, REFINE_ACTIONS, REFINE_RELAX, TONES, Brief, build_prompt, build_refine_prompt,
    get_copy_type, length_hint, parse_versions, refine_instruction, word_count,
)

BASE_DIR = Path(__file__).parent

# Every hint in the form describes the SAME example product, so users can see how one real
# brief fits together. Change them all together if you change the example.
PH = {
    "product": "e.g. Cotton summer kurta for men",
    "audience": "e.g. Young men, 18-30, in Pakistan",
    "qualities": "Soft breathable cotton\nStays the same size after washing\nSizes S to XXL",
    "offer": "e.g. Free delivery this week",
    "pain_points": "Shirts stick to your back in the heat\nCheap kurtas shrink after one wash",
    "cta": "e.g. Tap the link in bio and order yours today",
    "shots": "e.g. walking through a market, close-up of the fabric, folding the kurta",
    "keywords": "e.g. cotton kurta for men, summer kurta",
    "avoid": "e.g. cheap, best in Pakistan",
    "extra": "e.g. Available in white, navy and sand. Machine washable.",
    "refine": "e.g. mention free delivery in the last line",
}
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

sid = st.session_state.setdefault("sid", uuid.uuid4().hex[:6])   # ties one visit's messages together
WEBHOOK = get_setting("DISCORD_WEBHOOK_URL")

st.title("✍️ Copywriter AI")
st.caption("Pick what you need, fill the short form, get ready-to-use copy.")

# Fixed on purpose. These used to be settings; the people using the tool never needed them.
CREATIVITY = 0.8
VERSIONS = 3          # the AI always writes 3 versions; the app shows the best one
MAX_TONES = 4         # each tone costs one AI request
MODEL = get_setting("GEMINI_MODEL", DEFAULT_MODEL)   # developer-only, set as a secret
FALLBACKS = [m.strip() for m in get_setting(
    "GEMINI_FALLBACK_MODELS", ",".join(DEFAULT_FALLBACK_MODELS)).split(",") if m.strip()]

with st.sidebar:
    usage_box = st.empty()
    st.info("Free AI limits are small. If you hit a limit, wait a bit and retry. "
            "Don't enter confidential client details."
            + (" What you enter and what the AI writes is sent to the developer to help improve "
               "this tool." if WEBHOOK else ""))


def ai(system: str, user: str, temperature: float) -> str:
    """Every AI request goes through here, so the sidebar can count them.
    If the model has been renamed or retired, llm.generate switches to the backup by itself."""
    st.session_state["ai_requests"] = st.session_state.get("ai_requests", 0) + 1
    return generate(system, user, get_setting("GEMINI_API_KEY"), model=MODEL,
                    temperature=temperature, fallback_models=FALLBACKS)


def fix_fn(system: str, user: str) -> str:
    """Fixes should be careful, so use a lower creativity than the first draft."""
    return ai(system, user, min(CREATIVITY, 0.6))


def log_generation(brief: Brief, entries: list) -> None:
    """Send the full brief and ALL versions the AI wrote (shown and hidden) to Discord."""
    if not WEBHOOK:
        return
    settings = f"Settings: best of {VERSIONS}, creativity {CREATIVITY}, tone {brief.tone}, model {MODEL}"
    post_discord_async(WEBHOOK, generation_messages(
        sid, brief, entries, settings, st.session_state.get("ai_requests", 0)))


def log_followup(brief: Brief, item: dict) -> None:
    """Send a refined or fixed version to Discord."""
    if not WEBHOOK:
        return
    entry = dict(item, problems=run_checks(item["text"], brief, item.get("relax", "")))
    post_discord_async(WEBHOOK, followup_messages(
        sid, brief, entry, st.session_state.get("ai_requests", 0)))


def log_note(text: str) -> None:
    if WEBHOOK:
        post_discord_async(WEBHOOK, note_messages(sid, text))


# The type picker sits outside the form so the form below can change with it.
type_by_label = {ct.label: key for key, ct in COPY_TYPES.items()}
chosen = st.selectbox("What do you want to write?", list(type_by_label), key="copy_type_label")
ct = get_copy_type(type_by_label[chosen])

with st.form("brief"):
    product = st.text_input("What are you selling?*", key="product",
                            placeholder=PH["product"])
    audience = st.text_input("Who is it for?*", key="audience",
                             placeholder=PH["audience"])
    qualities = st.text_area("Key qualities* (one per line, 2-4 works best; ALL are used)", key="qualities",
                             placeholder=PH["qualities"])
    offer = st.text_input("Offer or discount (optional)", key="offer",
                          placeholder=PH["offer"])
    pain_points = st.text_area("Problems it solves (optional, one per line)", key="pain_points",
                               placeholder=PH["pain_points"])
    cta = (st.text_input("Exact call to action (optional)", key="cta",
                         placeholder=PH["cta"])
           if ct.supports_cta else "")
    c1, c2 = st.columns(2)
    language = c1.selectbox("Language", list(LANGUAGES), key="language")
    lengths = list(ct.lengths)
    length = c2.selectbox(ct.length_label, lengths, index=lengths.index(ct.default_length),
                          key=f"{ct.key}_length", format_func=lambda k: length_hint(ct, k))
    c3, c4 = st.columns(2)
    tones = c3.multiselect(
        "Tone (pick one or more)", TONES, default=[TONES[0]], max_selections=MAX_TONES, key="tones",
        help=f"Pick up to {MAX_TONES}. Each tone gets its own version and uses 1 AI request.")
    platform = c4.selectbox("Platform", ct.platforms, key=f"{ct.key}_platform")
    fmt_choice, shots = "", ""
    if ct.formats:
        fmt_choice = st.selectbox("Format", list(ct.formats), key=f"{ct.key}_format",
                                  help="Shot-by-shot gives timestamps with a visual, voiceover "
                                       "and on-screen text for each segment.")
        shots = st.text_area("Shots you can film (optional, used for shot-by-shot)",
                             key=f"{ct.key}_shots",
                             placeholder=PH["shots"])
    toggle_values = {}
    if ct.toggles:
        for col, (tkey, toggle) in zip(st.columns(len(ct.toggles)), ct.toggles.items()):
            toggle_values[tkey] = col.checkbox(toggle.label, value=toggle.default,
                                               key=f"{ct.key}_{tkey}")
    keywords = (st.text_input(ct.keywords_label, key=f"{ct.key}_keywords", placeholder=PH["keywords"])
                if ct.keywords_label else "")
    with st.expander("More options"):
        avoid = st.text_input("Words or claims to avoid", key="avoid", placeholder=PH["avoid"])
        extra = st.text_area("Extra details or specs (used only if there is space)", key="extra",
                         placeholder=PH["extra"])
    submitted = st.form_submit_button(f"Write my {ct.noun}", type="primary",
                                      use_container_width=True)

if submitted:
    brief = Brief(
        product=product, audience=audience, qualities=qualities.splitlines(), offer=offer,
        language=language, length=length, tone=tones[0] if tones else "", platform=platform,
        avoid=avoid, extra=extra, versions=VERSIONS, copy_type=ct.key, toggles=toggle_values,
        keywords=keywords, format=fmt_choice, pain_points=pain_points.splitlines(),
        shots=shots, cta=cta,
    )
    missing = brief.missing() + ([] if tones else ["tone"])
    if missing:
        st.warning("Please fill in: " + ", ".join(missing))
    else:
        items, failure = [], ""
        for tone in tones:                       # one request per tone, best of 3 for each
            tone_brief = replace(brief, tone=tone)
            system, user = build_prompt(tone_brief)
            try:
                with st.spinner(f"Writing ({tone})..." if len(tones) > 1 else "Writing..."):
                    text = ai(system, user, CREATIVITY)
            except LLMError as e:
                failure = f"{tone}: {e}" if len(tones) > 1 else str(e)
                break                            # the next tone would most likely fail the same way
            # Free fixes only (em dashes, unwanted emojis/hashtags). No AI request is used here.
            drafts = [f.text for f in auto_fix_many(tone_brief, parse_versions(text), fix_fn, 0)]
            if not drafts:
                failure = "The AI returned nothing. Try again."
                break
            order = rank_versions(drafts, tone_brief)
            best, hidden = order[0], order[1:]
            label = f"{tone} · " if len(tones) > 1 else ""
            items.append({
                "text": drafts[best], "note": f"{label}Best of {len(drafts)}", "relax": "",
                "brief": tone_brief, "alternates": [drafts[i] for i in hidden],
            })
            entries = []
            for rank, i in enumerate(order):
                shown = "Shown to the user (best of %d)" % len(drafts) if rank == 0 else f"Hidden option {rank}"
                entries.append({"text": drafts[i], "note": shown,
                                "problems": run_checks(drafts[i], tone_brief)})
            log_generation(tone_brief, entries)
        if items:
            st.session_state["result"] = {"brief": brief, "versions": items}
            if failure:
                st.warning(f"Couldn't write every tone. {failure}")
        else:
            st.session_state.pop("result", None)
            st.error(failure)

result = st.session_state.get("result")
if result:
    brief: Brief = result["brief"]
    result_type = get_copy_type(brief.copy_type)
    items = result["versions"]
    st.subheader(f"Your {result_type.noun}" + ("s" if len(items) > 1 else ""))
    st.caption(f"The AI wrote {VERSIONS} versions and this is the one that passed the most automatic "
               "checks. The checks can't judge taste, so use 'Show another option' to compare.")
    for idx, item in enumerate(list(items)):
        vbrief: Brief = item.get("brief", brief)       # each tone has its own brief
        n = idx + 1
        copy = item["text"]
        note = f"  ·  {item['note']}" if item["note"] else ""
        spoken = spoken_text(copy, vbrief)
        unit = "spoken words" if is_shot_list(vbrief) else "words"
        st.markdown(f"**Version {n}**{note}  ·  {word_count(spoken)} {unit} · {len(copy)} characters")
        st.code(copy, language=None, wrap_lines=True)  # copy button built in

        relax = item.get("relax", "")
        problems = run_checks(copy, vbrief, relax)
        if problems:
            for problem in problems:
                st.warning(problem)
            if st.button("🔧 Fix these problems", key=f"fix_{idx}"):
                with st.spinner("Fixing..."):
                    fix = auto_fix_many(vbrief, [copy], fix_fn, 2, relax=relax)[0]
                if fix.error:
                    st.error(fix.error)
                elif fix.text == copy:
                    st.info("I couldn't improve this version. Try Refine → Custom change.")
                else:
                    tail = "" if fix.fixed else " (some issues remain)"
                    result["versions"].append(
                        {"text": fix.text, "note": f"Fixed from version {n}{tail}", "relax": relax,
                         "brief": vbrief, "alternates": []})
                    log_followup(vbrief, result["versions"][-1])
                    st.rerun()
        else:
            st.caption("✅ Passed all automatic checks")

        others = item.get("alternates", [])
        if others and st.button(f"Show another option ({len(others)} left)", key=f"alt_{idx}"):
            result["versions"].append({"text": others.pop(0), "note": f"Another option from version {n}",
                                       "relax": "", "brief": vbrief, "alternates": []})
            log_note(f"User asked for another option (from version {n}, {vbrief.tone})")
            st.rerun()

        with st.expander(f"Refine version {n}"):
            action = st.selectbox("What should change?", list(REFINE_ACTIONS), key=f"ra_{idx}")
            new_tone = custom = ""
            if action == "Change the tone":
                new_tone = st.selectbox("New tone", TONES, key=f"rt_{idx}")
            if action == "Custom change":
                custom = st.text_input("Describe the change", key=f"rc_{idx}",
                                       placeholder=PH["refine"])
            if st.button("Refine", key=f"refine_{idx}"):
                instruction = refine_instruction(action, new_tone, custom)
                if not instruction:
                    st.warning("Please describe the change first.")
                else:
                    system, user = build_refine_prompt(vbrief, copy, instruction)
                    try:
                        with st.spinner("Refining..."):
                            text = ai(system, user, CREATIVITY)
                        revised = parse_versions(text)
                        if revised:
                            label = new_tone and f"{action}: {new_tone}" or action
                            new_text = revised[0]
                            new_relax = REFINE_RELAX.get(action, "")
                            note = f"Refined from version {n} ({label})"
                            new_text = auto_fix_many(vbrief, [new_text], fix_fn, 0)[0].text  # free fixes only
                            result["versions"].append(
                                {"text": new_text, "note": note, "relax": new_relax,
                                 "brief": vbrief, "alternates": []})
                            log_followup(vbrief, result["versions"][-1])
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
                        "copy_type": result_type.label, "format": vbrief.format,
                        "platform": vbrief.platform,
                        "product": vbrief.product, "audience": vbrief.audience,
                        "qualities": " | ".join(vbrief.qualities_clean), "offer": vbrief.offer,
                        "language": vbrief.language, "length": vbrief.length, "tone": vbrief.tone,
                        "version_note": item["note"], "script": copy, "rating": rating,
                        "whats_weak": weak, "expert_rewrite": rewrite,
                    }
                    save_feedback(row, FEEDBACK_FILE)
                    sent = notify_developer(row, get_setting("DISCORD_WEBHOOK_URL"))
                    st.success("Saved and sent. Thank you!" if sent else "Saved. Thank you!")

data = feedback_csv_bytes(FEEDBACK_FILE)
if data:
    st.divider()
    st.download_button("⬇️ Download all reviews (CSV)", data, "feedback.csv", "text/csv")
    st.caption("Tip: on the free hosted version, saved reviews can disappear when the app "
               "restarts, so download them regularly and send the file to the developer.")

usage_box.caption(f"AI requests this session: {st.session_state.get('ai_requests', 0)}")
