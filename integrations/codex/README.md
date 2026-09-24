# Codex integrations

This directory contains optional Codex-native integrations. They are isolated from Easel's
default OpenClaw runtime and do not change the existing `setup.sh`, `setup.ps1`, CLI, web
workspace, skills, profiles, or platform login state.

## Seal Private Operations V3

[`seal-private-operations-v3`](seal-private-operations-v3/) is a self-contained Codex Skill and
visual operations workspace for macOS and Windows. It keeps Easel's 113 capabilities inside one
Skill, adds recoverable operations tasks, and connects task context with chat, profiles, trends,
ideas, calendar items, content projects, publishing, and review.

- Product and Skill entry: [`seal-private-operations-v3/SKILL.md`](seal-private-operations-v3/SKILL.md)
- macOS install: `bash integrations/codex/seal-private-operations-v3/scripts/install-macos.sh`
- Windows install: `powershell -ExecutionPolicy Bypass -File .\integrations\codex\seal-private-operations-v3\scripts\install-windows.ps1`
- Default workspace: `http://127.0.0.1:7862/`
- Integrity check: `python integrations/codex/seal-private-operations-v3/scripts/verify_install.py`

The installer creates dependencies only inside the integration's `runtime/` directory, except
for missing platform prerequisites such as Python, Node.js, FFmpeg, and the official Codex CLI.
It does not install or start OpenClaw. Runtime state, credentials, cookies, browser profiles, and
generated content are ignored by Git and remain local.

External services are called only by the capability the user selects. Codex uses the local login
state; platform login and publishing use local browser sessions; RedFox and optional image,
video, music, voice, notification, and official publishing providers require their own keys.
See the [external-service reference](seal-private-operations-v3/references/运行原理与外部服务.md)
for the complete call and permission matrix.

The checked-in frontend `dist/` is intentional: it allows the Skill validator and runtime to work
immediately after checkout. Contributors changing the frontend should run `npm ci`, `npm run
build`, and commit the refreshed production bundle.
