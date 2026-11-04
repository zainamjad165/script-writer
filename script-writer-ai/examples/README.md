# Examples

Every `.json` file in this folder is read by the app. Each file is a list of examples:

```json
[
  {
    "type": "script",
    "language": "English",
    "length": "30 seconds",
    "platform": "Instagram Reels",
    "brief": {
      "product": "...",
      "audience": "...",
      "qualities": ["...", "..."],
      "offer": "..."
    },
    "script": "the finished copy, exactly as it should look"
  }
]
```

- `type` is one of: `script`, `caption`, `ad`, `product`. If left out, it counts as `script`.
- For `ad` and `product`, write the output in the labeled format the app produces
  (e.g. `HEADLINE:` / `PRIMARY TEXT:` / `CALL TO ACTION:`). See the starter files.
- The AI studies up to 3 examples of the same type per request, preferring the same language.
- Only add copy you wrote or have permission to use. Keep client confidential details out of public repos.
