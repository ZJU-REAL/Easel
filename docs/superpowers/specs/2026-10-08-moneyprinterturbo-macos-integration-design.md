# MoneyPrinterTurbo macOS Integration Design

## Summary

Add MoneyPrinterTurbo v1.3.7 to Easel as an isolated, optional short-video production engine on Apple Silicon macOS. The integration will support both one-shot headless generation and an optional local WebUI while preserving Easel as the owner of profiles, output layout, approval, publishing, and attribution.

The integration must not replace or modify the existing `auto-short-video` assembly pipeline. It will add new files at a narrow boundary so the current dirty video work remains untouched.

## Goals

- Install and verify the exact MoneyPrinterTurbo v1.3.7 source revision on Apple Silicon macOS.
- Generate a finished MP4 from a topic or prepared script through a one-shot Easel command.
- Support `9:16`, `16:9`, and `1:1` output, with the aspect ratio always supplied explicitly.
- Use the existing local OpenAI-compatible Qwen service for script generation by default.
- Default to non-billable inputs: local Qwen, Edge TTS, and user-provided local media.
- Allow free stock providers when their credentials are already configured.
- Require explicit per-run confirmation before any paid video-material provider is invoked.
- Deliver verified videos to `outputs/<human-readable-project>/final.mp4` and keep intermediate MoneyPrinterTurbo data isolated.
- Provide an optional loopback-only WebUI launcher for manual use.

## Non-goals

- Replacing Easel's current `auto-short-video` implementation.
- Adding a persistent MoneyPrinterTurbo API service.
- Changing Easel's profile, publishing, calendar, manifest, or attribution behavior.
- Automatically publishing a generated video.
- Enabling a paid image, video, music, or TTS provider without a separate explicit confirmation for the concrete run.
- Running multiple MoneyPrinterTurbo jobs concurrently.

## Runtime Layout

All persistent integration files remain inside the Easel project or its ignored runtime directories:

- Source checkout: `.tools/moneyprinterturbo/source`
- MoneyPrinterTurbo virtual environment: `.tools/moneyprinterturbo/source/.venv`
- MoneyPrinterTurbo configuration and task storage: `.state/moneyprinterturbo/`
- Easel delivery directory: `outputs/<human-readable-project>/`
- Easel skill: `skills/openclaw/moneyprinterturbo-video/`

The installer will pin both:

- Tag: `v1.3.7`
- Commit: `cf5a3aedad1741d012152d355aa909d224fc4557`

The checkout must not silently update to `main` or another tag.

The checkout's `config.toml` and `storage` entries will be integration-owned
symbolic links into `.state/moneyprinterturbo/`. The installer must reject
pre-existing links that resolve outside that state directory. This keeps
mutable configuration and task data separate from the pinned source checkout.

## Components

### Installer

Add `scripts/install-moneyprinterturbo.sh` with two modes:

- `--check`: perform read-only validation of macOS/arm64, `uv`, Git revision, Python environment, required imports, and FFmpeg.
- `--install`: clone the pinned revision into a staging directory, move it into place only after validation, run `uv sync --frozen`, and create the isolated runtime directories.

The installer must be idempotent. It must refuse to overwrite a dirty checkout, a non-Git path, or an existing checkout at the wrong revision. It must not install Docker, Conda, or packages into the system Python.

### Configuration

Add a configuration helper that creates or updates only the integration-owned MoneyPrinterTurbo configuration. It must not print configuration contents or credentials.

The default LLM configuration is:

- Provider: OpenAI-compatible
- Base URL: `http://127.0.0.1:8081/v1`
- Model: `qwen38-27b-mythos-agentic`
- API key placeholder: a non-secret local sentinel required by the client library

The base URL and model may be overridden through integration-specific environment variables. Credentials for optional stock providers are read from the Easel project `.env` or an existing integration-owned MoneyPrinterTurbo configuration without being echoed. The helper must not copy unrelated Easel secrets.

The integration does not start, stop, or reconfigure the Qwen service.

### Headless Bridge

Add `skills/openclaw/moneyprinterturbo-video/scripts/mpt_bridge.py` with a structured CLI. Required inputs are:

- Exactly one of `--topic` or `--script`
- `--project-name`
- `--aspect` with one of `9:16`, `16:9`, or `1:1`
- A material source

For `local`, one or more explicit material paths are required. Material paths must exist, must not be symlinks, and must remain within either the project-level `assets/` directory or the selected output project's `assets/` directory. Other project files, including `.env`, source code, and runtime state, are never valid media inputs. Online stock sources use their existing MoneyPrinterTurbo configuration.

The bridge will:

1. Validate all inputs and the destination through `skills/shared/scripts/output_paths.py`.
2. Acquire a single-job lock in `.state/moneyprinterturbo/`.
3. Build a subprocess argument array for the pinned `cli.py`; shell command strings are forbidden.
4. Invoke the command in the pinned checkout with a bounded long-running timeout.
5. Parse the single JSON result printed by MoneyPrinterTurbo.
6. Reject failed, missing, zero-byte, or non-MP4 results.
7. Copy the completed MP4 atomically to `outputs/<project-name>/final.mp4`.
8. Write a concise `brief.md` recording the engine version, aspect ratio, source type, and any non-sensitive degradation or warning.
9. Print a small machine-readable result containing only the final path, task ID, and status.

The bridge must preserve MoneyPrinterTurbo's task directory for repair and inspection. It must never treat an intermediate file as the final artifact.

### Provider Safety

Safe material providers are `local`, `pexels`, `pixabay`, and `coverr`. Missing credentials must produce a clear, non-secret error.

Paid providers are `volcengine_seedance`, `ofox`, and `metaso_minimax`. Selecting one requires the corresponding explicit bridge confirmation flag. The bridge passes MoneyPrinterTurbo's provider-specific charge flag only when the user has confirmed that provider for the current run. A generic confirmation flag is insufficient.

The integration will not add automatic retries after a paid task is submitted. A timeout after submission is reported as ambiguous and left for user review.

### WebUI Launcher

Add `start-moneyprinterturbo.command` for optional manual use. It will:

- Run the installer's `--check` mode before launch.
- Bind Streamlit only to `127.0.0.1`.
- Prefer port `8501` and use MoneyPrinterTurbo's existing safe fallback behavior when that port is occupied.
- Print the exact local WebUI URL.
- Run in the foreground so stopping the terminal stops the WebUI.

The launcher will not start the MoneyPrinterTurbo API server and will not bind to `0.0.0.0`.

### Easel Skill

Add `skills/openclaw/moneyprinterturbo-video/SKILL.md`. It will route requests that explicitly ask for MoneyPrinterTurbo or stock-footage-style topic-to-video generation.

The skill will preserve Easel's existing gates:

- Confirm aspect ratio before generation.
- Read the selected profile and preferences when present.
- Explain and obtain confirmation before paid operations.
- Use one human-readable output project.
- Self-check the final MP4 before delivery.
- Leave public publishing to the existing platform-specific skills.

## Error Handling

- Installation failures leave the previous verified installation untouched.
- Invalid or unsafe paths fail before MoneyPrinterTurbo starts.
- Missing credentials identify only the missing provider field and never display its value.
- A nonzero MoneyPrinterTurbo exit reports the failed stage and a bounded error excerpt.
- Timeouts clean up only bridge-owned temporary files; upstream task data remains available.
- The single-job lock reports the active job instead of launching a second concurrent render.
- Destination replacement is atomic so `final.mp4` is never partially written.

## Testing Strategy

Automated tests will cover:

- The pinned tag and commit, macOS/arm64 gate, idempotent `--check`, and refusal to overwrite unsafe installations.
- Topic-versus-script validation and mandatory explicit aspect ratio.
- Safe output-path validation and symlink rejection.
- Exact subprocess argument arrays for local, free-stock, and paid providers.
- Provider-specific confirmation gates and the absence of paid flags by default.
- Lock acquisition and concurrent-job rejection.
- JSON result parsing, missing/zero-byte/non-MP4 rejection, and atomic delivery.
- Redaction of credentials and internal configuration from errors and `brief.md`.
- Loopback-only launcher configuration.

After unit tests, verification will run the installer check, import the pinned runtime packages, boot the WebUI on loopback, query its health endpoint, and stop it. A full generated video is a separate paid-or-resource-using acceptance step and will run only after the user provides a topic, aspect ratio, material source, and any required confirmation.

## Acceptance Criteria

- `scripts/install-moneyprinterturbo.sh --install` completes on the current Apple Silicon Mac and `--check` subsequently passes.
- No existing dirty video-pipeline file is modified.
- The WebUI health endpoint responds on a loopback address and the server stops cleanly.
- A dry-run bridge invocation shows the exact safe command without exposing secrets.
- A fixture-backed integration test delivers a nonempty MP4 to a valid Easel output project.
- Paid provider selection fails closed unless its exact confirmation flag is present.
- No publication occurs as part of installation or generation.
