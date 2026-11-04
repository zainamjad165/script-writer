# 🎬 Script Writer AI

Writes short video scripts (Reels / TikTok / Shorts / ads) in a fixed structure:

1. **Hook**: one question the viewer cares about
2. **Body**: what the product offers
3. **End**: the offer + a clear call to action

Languages: English, Roman Urdu, Urdu. Lengths: 15 / 30 / 60 seconds.
Everything here is **free**: free Gemini API key, free Streamlit hosting, free GitHub.

> Status: v1 for expert testing. The built-in examples are placeholders; real expert
> scripts will make it much better (see "Teach it your style").

## Try it (for the tester)

Open the app link you were sent, fill the form, press **Write my script**.
Under each version, open **Review** and tell us what's weak, and if you can, how *you*
would write it. Then press **Download all reviews (CSV)** and send us the file.

## Run it yourself

1. Install Python 3.10+.
2. Get a free key: https://aistudio.google.com -> **Get API key**.
3. In the project folder:
   ```bash
   pip install -r requirements.txt
   cp .env.example .env        # then open .env and paste your key
   streamlit run app.py
   ```

## Put it online for free (Streamlit Community Cloud)

1. Push this repo to GitHub (`.env` is already git-ignored, **never commit your key**).
2. Go to https://share.streamlit.io -> **New app** -> pick the repo -> main file `app.py`.
3. **Advanced settings -> Secrets**, paste:
   ```toml
   GEMINI_API_KEY = "your-key"
   APP_PASSWORD = "choose-a-password"   # optional but recommended
   ```
4. Share the app link (and the password) with the tester.

## Teach it your style (no coding)

- **`rules.md`**: the expert's rules and tips. Edit it directly on GitHub.
- **`examples/`**: add a `.json` file with real scripts, same format as
  `examples/starter_examples.json`: `language`, `length`, `brief`, `script`.
  The AI studies up to 3 matching examples per request.

## Good to know

- **Free tier limits are small** and change often. If you see a limit error, wait and retry.
- On Google's free tier, your inputs may be used to improve Google's products.
  Don't enter confidential client details.
- Model not found? Change the model in the sidebar (try `gemini-flash-latest`) or set
  `GEMINI_MODEL`.
- Saved reviews live in `feedback/feedback.csv`; on free hosting they can vanish on restart,
  so download them regularly.

## Develop

```bash
python -m pytest        # runs all tests (no API key needed)
```

Files: `app.py` (UI) · `prompt.py` (builds the prompt) · `llm.py` (Gemini client) ·
`rules.md` · `examples/` · `tests/`

## Roadmap

- [ ] Real expert examples + rules
- [ ] Other copy types (ads, captions, product descriptions)
- [ ] Hook-style presets from expert feedback
