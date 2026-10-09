# MoneyPrinterTurbo macOS Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install pinned MoneyPrinterTurbo v1.3.7 on this Apple Silicon Mac and expose it as a safe, one-shot Easel video-production backend with optional loopback WebUI access.

**Architecture:** A pinned installer owns the external checkout and runtime links, while a new `easel.moneyprinterturbo` adapter validates requests, configures the local Qwen provider, invokes the upstream CLI, and atomically delivers verified MP4s into Easel outputs. A thin skill CLI and `.command` launcher expose the headless and WebUI paths without modifying the existing `auto-short-video` pipeline.

**Tech Stack:** Bash, Python 3.11+, `uv`, MoneyPrinterTurbo CLI, pytest, Streamlit, FFmpeg.

**Spec:** `docs/superpowers/specs/2026-10-08-moneyprinterturbo-macos-integration-design.md`

## Global Constraints

- Support Apple Silicon macOS only: `uname -s` must be `Darwin` and `uname -m` must be `arm64`.
- Pin MoneyPrinterTurbo tag `v1.3.7` and commit `cf5a3aedad1741d012152d355aa909d224fc4557`; never follow `main`.
- Use `uv sync --frozen`; do not install Docker, Conda, or packages into system Python.
- Keep source under `.tools/moneyprinterturbo/source` and mutable configuration/storage under `.state/moneyprinterturbo/`.
- Never modify the existing dirty video-pipeline files or the existing `auto-short-video` implementation.
- Require exactly one of topic or script, a human-readable project name, and an explicit `9:16`, `16:9`, or `1:1` aspect ratio.
- Default to local Qwen, Edge TTS, local media, and no publication.
- Never pass a paid-provider confirmation flag without exact per-provider confirmation for that run.
- Accept local media only from `assets/` or `outputs/<project>/assets/`; reject symlinks and every other project path.
- Deliver only a verified nonempty MP4 to `outputs/<project>/final.mp4`; preserve upstream task state for repair.
- Never print credentials, full configuration, or unbounded upstream errors.

## Review Focus

- An existing non-Git, dirty, or wrong-revision runtime must be rejected without deleting or overwriting it; covered in Task 1 installer tests.
- Local-media symlinks and paths such as `.env`, `.state`, sibling projects, or `..` escapes must fail before subprocess launch; covered in Task 2 validation tests.
- Upstream stdout containing malformed JSON, multiple JSON objects, a mismatched task ID, or a video path outside the matching task directory must fail closed; covered in Task 3 result tests.
- A timeout after launching a paid provider must be reported as ambiguous and must not be retried; covered in Task 3 runner tests.
- Replacing an existing final video must be atomic, preserving the previous file when staging or copy fails; covered in Task 3 delivery tests.

---

### Task 1: Pinned Runtime Installer

**Files:**
- Create: `scripts/install-moneyprinterturbo.sh`
- Create: `tests/test_moneyprinterturbo_install.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Git, `uv`, FFmpeg, the project root, and network access only in `--install` mode.
- Produces: `scripts/install-moneyprinterturbo.sh (--check|--install) [--root PATH]`, a verified checkout at `<root>/.tools/moneyprinterturbo/source`, and safe state links into `<root>/.state/moneyprinterturbo/`.

- [ ] **Step 1: Write failing installer contract tests**

Add tests named:

```python
def test_installer_pins_tag_commit_and_frozen_uv_sync(): ...
def test_check_rejects_missing_non_git_wrong_revision_and_dirty_source(tmp_path): ...
def test_installer_never_deletes_an_unsafe_existing_path(tmp_path): ...
def test_runtime_links_must_resolve_inside_moneyprinterturbo_state(tmp_path): ...
def test_moneyprinterturbo_runtime_directories_are_gitignored(): ...
```

The subprocess tests call `bash scripts/install-moneyprinterturbo.sh --check --root <tmp>` and assert nonzero status plus bounded diagnostics. The static contract test asserts the exact tag, commit, `uv sync --frozen`, staging-directory move, and absence of Docker/Conda/system-pip installation commands.

- [ ] **Step 2: Run installer tests and verify RED**

Run: `python -m pytest tests/test_moneyprinterturbo_install.py -q`

Expected: FAIL because the installer and ignore entries do not exist.

- [ ] **Step 3: Implement the installer**

Implement `--check` and `--install` with:

- `MPT_TAG=v1.3.7` and `MPT_COMMIT=cf5a3aedad1741d012152d355aa909d224fc4557`.
- Root resolution relative to the script, with optional `--root` for tests and recovery.
- Read-only platform, tool, revision, clean-worktree, `.venv`, import, FFmpeg, link-target, and state-directory checks.
- A staged clone inside `.tools/moneyprinterturbo/`, detached checkout of the exact commit, `uv sync --frozen`, then atomic directory move.
- Refusal to replace an existing non-Git path, dirty checkout, wrong revision, or external symlink.
- State directories `.state/moneyprinterturbo/storage` and `.state/moneyprinterturbo/config.toml`; initialize the config from `config.example.toml` only when absent.
- Relative links from the source checkout's `config.toml` and `storage` into the state directory.
- Targeted `.gitignore` entries for `.tools/moneyprinterturbo/` and `.state/moneyprinterturbo/`.

- [ ] **Step 4: Run installer tests and verify GREEN**

Run: `python -m pytest tests/test_moneyprinterturbo_install.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the installer task**

```bash
git add .gitignore scripts/install-moneyprinterturbo.sh tests/test_moneyprinterturbo_install.py
git commit -m "feat: add pinned MoneyPrinterTurbo installer"
```

### Task 2: Request Validation, Managed Configuration, and Command Construction

**Files:**
- Create: `easel/moneyprinterturbo.py`
- Create: `tests/test_moneyprinterturbo.py`

**Interfaces:**
- Consumes: the installer layout from Task 1 and `skills.shared.scripts.output_paths`.
- Produces:
  - `MoneyPrinterTurboError(RuntimeError)`
  - `MoneyPrinterTurboPaths.for_root(root: Path) -> MoneyPrinterTurboPaths`
  - `MoneyPrinterTurboRequest` frozen dataclass
  - `PreparedMoneyPrinterTurboRequest` frozen dataclass
  - `prepare_request(paths: MoneyPrinterTurboPaths, request: MoneyPrinterTurboRequest) -> PreparedMoneyPrinterTurboRequest`
  - `render_managed_config(example_text: str, *, llm_base_url: str, llm_model: str) -> str`
  - `configure_managed_runtime(paths: MoneyPrinterTurboPaths, *, llm_base_url: str, llm_model: str) -> None`
  - `build_command(paths: MoneyPrinterTurboPaths, request: PreparedMoneyPrinterTurboRequest, task_id: str) -> list[str]`

- [ ] **Step 1: Write failing request-validation tests**

Add focused tests asserting:

```python
def test_request_requires_exactly_one_topic_or_script_and_explicit_aspect(tmp_path): ...
def test_project_name_uses_output_paths_gate(tmp_path, monkeypatch): ...
def test_local_source_requires_real_non_symlink_media_in_allowed_roots(tmp_path): ...
def test_project_secrets_state_source_and_other_output_projects_are_not_media(tmp_path): ...
def test_safe_stock_sources_need_no_charge_confirmation(tmp_path): ...
def test_each_paid_source_requires_only_its_matching_confirmation(tmp_path): ...
```

Use real temporary files under `<root>/assets/` and `<root>/outputs/<project>/assets/`; do not mock path resolution.

- [ ] **Step 2: Run validation tests and verify RED**

Run: `python -m pytest tests/test_moneyprinterturbo.py -q -k 'request or source or media or project_name'`

Expected: FAIL because the adapter module does not exist.

- [ ] **Step 3: Implement paths and request validation**

`MoneyPrinterTurboRequest` has these exact fields:

```python
project_name: str
aspect: str
source: str
topic: str | None = None
script: str | None = None
materials: tuple[Path, ...] = ()
confirm_seedance_charge: bool = False
confirm_ofox_charge: bool = False
confirm_metaso_minimax_charge: bool = False
```

`prepare_request` validates the content gate, source set, matching confirmation, allowed material roots, symlinks, extensions, and destination through `validate_project_dir`. It resolves the destination as `<project>/final.mp4` without creating it during validation.

- [ ] **Step 4: Write failing managed-config and command tests**

Add tests named:

```python
def test_managed_config_sets_loopback_local_qwen_and_disables_upload(): ...
def test_managed_config_preserves_unowned_provider_credentials(): ...
def test_local_command_is_an_argv_array_with_explicit_aspect_and_materials(): ...
def test_safe_stock_commands_have_no_paid_flags(): ...
def test_paid_commands_add_only_the_matching_upstream_confirmation(): ...
def test_topic_and_script_map_to_distinct_upstream_arguments(): ...
```

- [ ] **Step 5: Run managed-config and command tests and verify RED**

Run: `python -m pytest tests/test_moneyprinterturbo.py -q -k 'config or command or paid'`

Expected: FAIL because the functions are not implemented.

- [ ] **Step 6: Implement managed configuration and command construction**

`render_managed_config` performs section-aware replacement of only these fields:

- top level: `listen_host = "127.0.0.1"`
- `[app]`: `llm_provider = "openai"`, `openai_api_key = "local-easel"`, `openai_base_url`, `openai_model_name`, `upload_post_enabled = false`, and `upload_post_auto_upload = false`

Preserve all other values, including optional stock credentials already configured through the WebUI. `configure_managed_runtime` writes through a same-directory temporary file, fsyncs, and atomically replaces the state-owned config. `build_command` returns an argv list beginning with the pinned `.venv/bin/python`, `cli.py`, and `--task-id`; it never uses `shell=True` or embeds a shell command string.

- [ ] **Step 7: Run all Task 2 tests and verify GREEN**

Run: `python -m pytest tests/test_moneyprinterturbo.py -q`

Expected: PASS for the validation/configuration/command tests implemented so far.

- [ ] **Step 8: Commit the adapter foundation**

```bash
git add easel/moneyprinterturbo.py tests/test_moneyprinterturbo.py
git commit -m "feat: validate MoneyPrinterTurbo generation requests"
```

### Task 3: One-shot Execution, Result Verification, and Atomic Delivery

**Files:**
- Modify: `easel/moneyprinterturbo.py`
- Modify: `tests/test_moneyprinterturbo.py`
- Create: `skills/openclaw/moneyprinterturbo-video/scripts/mpt_bridge.py`

**Interfaces:**
- Consumes: Task 2's prepared request and command builder.
- Produces:
  - `BridgeResult(status: str, task_id: str, final_path: Path, warnings: tuple[str, ...])`
  - `parse_cli_result(stdout: str, *, expected_task_id: str, task_root: Path) -> tuple[Path, tuple[str, ...]]`
  - `atomic_deliver(source: Path, destination: Path) -> None`
  - `MoneyPrinterTurboBridge.run(request: MoneyPrinterTurboRequest, *, dry_run: bool = False) -> BridgeResult | list[str]`
  - CLI subcommands `configure`, `run`, and `dry-run`; exit `0` plus a small JSON result on success, `2` for invalid input, and `1` for runtime failure.

- [ ] **Step 1: Write failing result and delivery tests**

Add tests named:

```python
def test_result_accepts_one_matching_completed_task_video(tmp_path): ...
def test_result_rejects_malformed_multiple_or_mismatched_json(tmp_path): ...
def test_result_rejects_missing_empty_non_mp4_and_out_of_task_paths(tmp_path): ...
def test_atomic_delivery_replaces_only_after_complete_copy(tmp_path, monkeypatch): ...
def test_atomic_delivery_preserves_existing_final_when_copy_fails(tmp_path, monkeypatch): ...
```

Use an upstream-shaped payload: `{"task_id": id, "result": {"videos": [path], "warnings": [...]}}`.

- [ ] **Step 2: Run result tests and verify RED**

Run: `python -m pytest tests/test_moneyprinterturbo.py -q -k 'result or delivery'`

Expected: FAIL because result parsing and delivery are absent.

- [ ] **Step 3: Implement strict result parsing and atomic delivery**

Require exactly one JSON object, the expected task ID, exactly one final video, and a resolved source under `.state/moneyprinterturbo/storage/tasks/<task-id>/`. Stage the copy in the destination directory, flush and fsync it, then `os.replace`; remove only the bridge-owned staging file on failure.

- [ ] **Step 4: Write failing bridge-runner tests**

Add tests named:

```python
def test_dry_run_returns_redacted_argv_without_launching(tmp_path): ...
def test_bridge_writes_managed_config_runs_once_and_delivers_brief(tmp_path): ...
def test_single_job_lock_rejects_concurrent_run(tmp_path): ...
def test_nonzero_exit_reports_bounded_redacted_error(tmp_path): ...
def test_safe_timeout_is_not_retried(tmp_path): ...
def test_paid_timeout_is_ambiguous_and_is_not_retried(tmp_path): ...
def test_bridge_cli_configure_run_and_dry_run_contract(tmp_path): ...
def test_bridge_cli_prints_only_small_result_json(tmp_path): ...
```

Inject a recording `runner` and deterministic task-ID factory. The successful fake runner creates a real nonempty MP4 inside the matching task directory and returns upstream-shaped JSON.

- [ ] **Step 5: Run bridge tests and verify RED**

Run: `python -m pytest tests/test_moneyprinterturbo.py -q -k 'bridge or lock or timeout or dry_run or nonzero'`

Expected: FAIL because the bridge and CLI do not exist.

- [ ] **Step 6: Implement the bridge and thin skill CLI**

Use `fcntl.flock(..., LOCK_EX | LOCK_NB)` for crash-safe single-job exclusion. Run the command once with `cwd=paths.source`, `capture_output=True`, `text=True`, `shell=False`, and a default 20-minute timeout. Bound error excerpts to 1,000 characters after replacing configured secret values with `[REDACTED]`. Write `brief.md` with version, aspect, source, warnings, and no credentials. The CLI uses argparse and delegates all behavior to `easel.moneyprinterturbo`.

- [ ] **Step 7: Run all adapter tests and verify GREEN**

Run: `python -m pytest tests/test_moneyprinterturbo.py -q`

Expected: PASS.

- [ ] **Step 8: Commit one-shot execution**

```bash
git add easel/moneyprinterturbo.py tests/test_moneyprinterturbo.py skills/openclaw/moneyprinterturbo-video/scripts/mpt_bridge.py
git commit -m "feat: add MoneyPrinterTurbo one-shot bridge"
```

### Task 4: Easel Skill and Loopback WebUI Launcher

**Files:**
- Create: `skills/openclaw/moneyprinterturbo-video/SKILL.md`
- Create: `skills/openclaw/moneyprinterturbo-video/EASEL-META.md`
- Create: `start-moneyprinterturbo.command`
- Create: `tests/test_moneyprinterturbo_surfaces.py`

**Interfaces:**
- Consumes: Task 1 installer and Task 3 bridge CLI.
- Produces: an Easel skill route and a foreground-only WebUI launcher at `http://127.0.0.1:8501` with upstream port fallback.

- [ ] **Step 1: Write failing surface-contract tests**

Add tests named:

```python
def test_skill_routes_explicit_moneyprinterturbo_and_stock_video_requests(): ...
def test_skill_requires_aspect_profile_checks_and_paid_confirmation(): ...
def test_skill_delivers_to_easel_outputs_and_never_publishes(): ...
def test_launcher_checks_installation_and_binds_loopback_only(): ...
def test_launcher_starts_only_webui_in_foreground(): ...
```

Assert that the launcher contains `MPT_WEBUI_HOST=127.0.0.1`, port `8501`, and `webui.sh`; assert it does not contain `0.0.0.0`, `main.py`, background `&`, or API startup.

- [ ] **Step 2: Run surface tests and verify RED**

Run: `python -m pytest tests/test_moneyprinterturbo_surfaces.py -q`

Expected: FAIL because the skill and launcher do not exist.

- [ ] **Step 3: Implement the skill and launcher**

The skill must instruct the agent to:

- Change to the Easel project root and confirm `.env` plus `skills/shared/scripts/` before the first project script.
- Confirm aspect ratio before generation.
- Read the selected profile's production-relevant files when supplied.
- Run the installer check, then the bridge as one foreground command.
- Explain provider scope/cost and require exact confirmation before paid flags.
- Validate final existence, nonzero size, MP4 format, resolution, and aspect before delivery.
- Route publishing to existing publisher skills only after generation.

The launcher resolves its own project root, runs installer `--check`, runs the bridge's `configure` subcommand so a first launch uses local Qwen, exports the loopback host and preferred port, prints the URL through upstream `webui.sh`, and remains foreground-bound.

- [ ] **Step 4: Run surface tests and verify GREEN**

Run: `python -m pytest tests/test_moneyprinterturbo_surfaces.py -q`

Expected: PASS.

- [ ] **Step 5: Commit user-facing surfaces**

```bash
git add skills/openclaw/moneyprinterturbo-video start-moneyprinterturbo.command tests/test_moneyprinterturbo_surfaces.py
git commit -m "feat: expose MoneyPrinterTurbo through Easel"
```

### Task 5: Install and Verify on the Mac

**Files:**
- Runtime only, ignored: `.tools/moneyprinterturbo/`, `.state/moneyprinterturbo/`
- Modify only if verification finds a documented defect: files created in Tasks 1-4 and their tests

**Interfaces:**
- Consumes: all implementation tasks.
- Produces: a verified local installation, passing tests, a working loopback WebUI, and a safe dry-run command.

- [ ] **Step 1: Run all targeted tests**

Run:

```bash
python -m pytest tests/test_moneyprinterturbo_install.py tests/test_moneyprinterturbo.py tests/test_moneyprinterturbo_surfaces.py -q
```

Expected: PASS with zero failures.

- [ ] **Step 2: Run the complete Easel test suite**

Run: `python -m pytest tests -q`

Expected: PASS. If unrelated pre-existing failures occur, record each failing test by name and confirm the targeted suite remains green before proceeding.

- [ ] **Step 3: Install the pinned runtime**

Run: `bash scripts/install-moneyprinterturbo.sh --install`

Expected: exit `0`, exact pinned revision installed, no secrets printed.

- [ ] **Step 4: Verify installation and links**

Run: `bash scripts/install-moneyprinterturbo.sh --check`

Expected: exit `0` and a concise `ready` status. Independently verify `config.toml` and `storage` resolve inside `.state/moneyprinterturbo/` without printing config content.

- [ ] **Step 5: Verify bridge dry run**

Run the bridge with a concrete human-readable project, explicit aspect, `--source pexels`, and `dry-run`. A dry run must not require or validate a Pexels key because it makes no provider request. Confirm the argv contains no paid confirmation and no secret value and that no output project was created.

- [ ] **Step 6: Smoke-test the WebUI**

Launch `start-moneyprinterturbo.command` in a resumable foreground terminal, wait for its printed loopback URL, request `/_stcore/health`, require `ok`, then send Ctrl-C and verify the port is no longer listening.

- [ ] **Step 7: Review the final diff and runtime state**

Run `git diff --check`, inspect only the implementation files, confirm no existing dirty pipeline file changed, and run the targeted tests once more after any repair.

- [ ] **Step 8: Commit verification-only repairs if needed**

If verification required code changes, follow RED-GREEN first and commit only those implementation/test files:

```bash
git commit -m "fix: harden MoneyPrinterTurbo macOS integration"
```

Do not generate a full social video in this task. That acceptance run requires a user-selected topic or script, explicit aspect ratio, material source, and any provider confirmation required by the selected source.
