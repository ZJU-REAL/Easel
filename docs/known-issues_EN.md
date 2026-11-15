# Known Issues

This page tracks known issues relevant to using Easel, along with recommended workarounds. If you hit something not listed here, please open an [Issue](https://github.com/ZJU-REAL/Easel/issues).

---

## QR login on WeChat Official Accounts and Toutiao

- **WeChat Official Accounts show a full-page image or an invalidated QR code**: remembered accounts may open the quick-login view. Easel waits for the scan-login control and switches at most once per login attempt, then saves only a detected QR pattern. It clicks the explicit refresh link only in an expired or failed QR overlay; a successful scan is left awaiting confirmation.
- **Toutiao reports phone binding before showing a QR code**: the phone-login form and QR code can coexist, and the code may load asynchronously or in an iframe. Easel waits for and validates the QR image and updates it during polling. A brief gap during code rotation does not immediately end login. Persistent phone verification still requires the account owner to finish in the visible browser window.

Scanning alone does not establish a saved login session. These fixes do not bypass administrator confirmation, phone verification, network failures, or platform risk controls.

---

## Duplicate reply after an "ask_user" prompt in the CLI chat

- **Scope**: `easel chat` (terminal chat) only. **The Web workspace is unaffected.**
- **Symptom**: After the Agent raises an `ask_user` prompt and you answer it, the Agent's next reply may be rendered twice in the terminal (the content is correct — it just shows up twice).
- **Nature**: This is a **display-only** issue. It does not affect the actual conversation content, asset generation, or publishing results.

### Root cause

The issue lives in the **session projection** logic of upstream [OpenClaw](https://www.npmjs.com/package/openclaw), not in the Easel repository.

`easel chat` runs `openclaw tui` under the hood, and OpenClaw's gateway-client rebuilds the transcript in the terminal. When a live reply is mistakenly matched against another row (e.g. the `ask_user` prompt row) and the two do not share a transcript identity, the projection re-inserts the reply, causing the duplicate render.

We verified this root cause and reproduced it in upstream regression tests (3 related cases failed before the fix and all pass after it).

### Upstream fix status

The fix has been submitted to OpenClaw. Tracking PRs:

- openclaw#144730
- openclaw#144892

The fix uses a four-layer strategy: unique full-content match, required terminal evidence, a tentative recovery record, and keeping a distinct later final visible when tentative recovery cannot represent it.

### Workaround and upgrade

- **Recommended**: use the **Web workspace** (`easel web`, `http://localhost:7860` by default). The Web backend renders from the raw event stream itself and does not go through the session-projection logic above, so it is **unaffected** by this issue — and it offers a more complete experience (conversations, assets, accounts, profiles, content library, and publishing management) than the CLI.
- If you prefer `easel chat`: once upstream ships a release with the fix, upgrading OpenClaw resolves it:

  ```bash
  npm i -g openclaw@latest
  ```

- Easel installs the OpenClaw global CLI (a prebuilt artifact), so we **do not vendor the patch inside the Easel repo**; instead we track the latest upstream release. `easel doctor` already checks the minimum OpenClaw version (≥ 2026.6.11) and prompts users to upgrade when it is too old.
