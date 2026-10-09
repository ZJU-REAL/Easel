---
name: moneyprinterturbo-video
description: "Use the pinned MoneyPrinterTurbo backend on Apple Silicon macOS for an explicit MoneyPrinterTurbo request or a one-shot short video assembled from local media or Pexels, Pixabay, or Coverr stock video. Produces one verified MP4 and never publishes it automatically."
layer: produce
version: 0.1.0
profile_aware: true
---

# MoneyPrinterTurbo video

Use this production skill when the user explicitly asks for MoneyPrinterTurbo, or wants a stock footage / stock video short assembled from local media, Pexels, Pixabay, or Coverr. Keep the existing `auto-short-video` route for Easel's native multi-skill pipeline.

## Required input

- Exactly one topic or finished script.
- A human-readable project name.
- An explicitly confirmed aspect: `9:16`, `16:9`, or `1:1`. Ask before generation when it is missing; never infer it silently.
- One source: `local`, `pexels`, `pixabay`, `coverr`, `volcengine_seedance`, `ofox`, or `metaso_minimax`.
- For `local`, one or more real media files under project `assets/` or `outputs/<project>/assets/`.

If a Profile is selected, read its production-relevant `identity.md`, `style.md`, `audience.md`, `preferences.md`, and `memory.md`. Apply the preferences red lines verbatim. Production does not read `platforms.md`.

## Cost gate

Explain source scope and cost before a paid request. Local media and configured Pexels, Pixabay, or Coverr stock providers do not need a charge flag. The paid sources require a fresh, exact confirmation for the current run:

- `volcengine_seedance` → `--confirm-seedance-charge`
- `ofox` → `--confirm-ofox-charge`
- `metaso_minimax` → `--confirm-metaso-minimax-charge`

Never substitute a generic confirmation or pass a different provider's flag. A timeout from a paid source is ambiguous and must not be retried automatically.

## Run from the project root

Before the first project script, change to the Easel project root and verify both `.env` and `skills/shared/scripts/` exist. Do not print `.env`.

```bash
cd "/absolute/path/to/Easel"
test -f .env
test -d skills/shared/scripts/
scripts/install-moneyprinterturbo.sh --check
```

Run exactly one bridge command in the foreground. Start with `dry-run` when checking a request; replace it with `run` only after the aspect and any paid cost confirmation are settled.

```bash
.venv/bin/python skills/openclaw/moneyprinterturbo-video/scripts/mpt_bridge.py dry-run \
  --root "$PWD" --project "<project>" --aspect "9:16" \
  --source pexels --topic "<topic>"

.venv/bin/python skills/openclaw/moneyprinterturbo-video/scripts/mpt_bridge.py run \
  --root "$PWD" --project "<project>" --aspect "9:16" \
  --source pexels --topic "<topic>"
```

For a script, use `--script` instead of `--topic`. For local media, repeat `--material <path>`. Add only the selected paid source's confirmed flag.

## Verify and deliver

The bridge delivers only to `outputs/<project>/final.mp4` and writes a non-sensitive `brief.md`. Before calling it complete:

1. Confirm the file exists, has nonzero size, and is an MP4.
2. Use `ffprobe` to read width, height, and duration.
3. Verify the measured resolution matches the confirmed `9:16`, `16:9`, or `1:1` aspect.
4. Report any bridge warnings or degradation without exposing configuration or credentials.

Never publish automatically. If the user separately asks to publish after generation, route the verified MP4 to the matching existing publisher skill, including the normal persona and content-safety gates.

## Optional WebUI

`start-moneyprinterturbo.command` opens the upstream WebUI in the foreground on loopback, preferring `http://127.0.0.1:8501`. It is for interactive local configuration and inspection; the bridge remains the controlled delivery path.
