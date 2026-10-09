#!/usr/bin/env bash

set -euo pipefail

MPT_TAG=v1.3.7
MPT_COMMIT=cf5a3aedad1741d012152d355aa909d224fc4557
MPT_REPOSITORY=https://github.com/harry0703/MoneyPrinterTurbo.git

fail() {
  printf 'MoneyPrinterTurbo: %s\n' "$*" >&2
  return 1
}

check_platform() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "unsupported platform; Apple Silicon macOS is required"
  [[ "$(uname -m)" == "arm64" ]] || fail "unsupported architecture; arm64 is required"
}

check_tools() {
  local tool
  for tool in git uv ffmpeg; do
    command -v "$tool" >/dev/null 2>&1 || fail "missing required tool: $tool"
  done
}

check_source_checkout() {
  local checkout=$1
  local expected_commit=$2
  local actual_commit status status_line runtime_name

  [[ -e "$checkout" || -L "$checkout" ]] || fail "source checkout is missing: $checkout"
  [[ ! -L "$checkout" ]] || fail "source checkout must not be a symlink: $checkout"
  [[ -d "$checkout/.git" ]] || fail "source path is not a Git checkout: $checkout"

  actual_commit=$(git -C "$checkout" rev-parse HEAD 2>/dev/null) || fail "cannot read source revision"
  [[ "$actual_commit" == "$expected_commit" ]] || fail "source checkout has wrong revision: $actual_commit"

  status=$(git -C "$checkout" status --porcelain --untracked-files=all 2>/dev/null) || fail "cannot inspect source checkout"
  while IFS= read -r status_line; do
    [[ -n "$status_line" ]] || continue
    case "$status_line" in
      "?? storage"|"?? config.toml")
        runtime_name=${status_line:3}
        [[ -L "$checkout/$runtime_name" ]] && continue
        ;;
    esac
    fail "source checkout is dirty; preserve or remove those changes manually"
  done <<< "$status"
}

check_managed_link() {
  local link_path=$1
  local expected_path=$2
  local actual expected

  [[ -L "$link_path" ]] || fail "managed runtime link is missing: $link_path"
  actual=$(realpath "$link_path" 2>/dev/null) || fail "managed runtime link is broken: $link_path"
  expected=$(realpath "$expected_path" 2>/dev/null) || fail "managed state target is missing: $expected_path"
  [[ "$actual" == "$expected" ]] || fail "managed runtime link has unexpected target: $link_path"
}

ensure_managed_link() {
  local link_path=$1
  local target_path=$2
  local relative_target=$3

  if [[ -e "$link_path" || -L "$link_path" ]]; then
    check_managed_link "$link_path" "$target_path"
    return
  fi
  ln -s "$relative_target" "$link_path"
  check_managed_link "$link_path" "$target_path"
}

check_runtime() {
  local root=$1
  local source_dir="$root/.tools/moneyprinterturbo/source"
  local state_dir="$root/.state/moneyprinterturbo"

  check_platform
  check_tools
  check_source_checkout "$source_dir" "$MPT_COMMIT"
  [[ -d "$state_dir" && ! -L "$state_dir" ]] || fail "managed state directory is missing or unsafe: $state_dir"
  [[ -f "$state_dir/config.toml" && ! -L "$state_dir/config.toml" ]] || fail "managed config is missing or unsafe"
  [[ -d "$state_dir/storage" && ! -L "$state_dir/storage" ]] || fail "managed storage is missing or unsafe"
  check_managed_link "$source_dir/config.toml" "$state_dir/config.toml"
  check_managed_link "$source_dir/storage" "$state_dir/storage"
  [[ -x "$source_dir/.venv/bin/python" ]] || fail "managed Python environment is missing"
  "$source_dir/.venv/bin/python" -c \
    'import fastapi, moviepy, streamlit, faster_whisper, ctranslate2, edge_tts' \
    >/dev/null 2>&1 || fail "managed Python imports failed"
}

install_runtime() {
  local root=$1
  local tools_dir="$root/.tools/moneyprinterturbo"
  local source_dir="$tools_dir/source"
  local state_dir="$root/.state/moneyprinterturbo"
  local stage_source="$tools_dir/.source.partial.$$"
  local config_stage="$state_dir/.config.toml.partial.$$"

  check_platform
  check_tools

  if [[ -e "$source_dir" || -L "$source_dir" ]]; then
    check_source_checkout "$source_dir" "$MPT_COMMIT"
  else
    mkdir -p "$tools_dir"
    [[ ! -e "$stage_source" && ! -L "$stage_source" ]] || fail "staging path already exists: $stage_source"
    git clone --filter=blob:none --branch "$MPT_TAG" --single-branch "$MPT_REPOSITORY" "$stage_source"
    check_source_checkout "$stage_source" "$MPT_COMMIT"
    (
      cd "$stage_source"
      uv sync --frozen
    )
    [[ ! -e "$source_dir" && ! -L "$source_dir" ]] || fail "source path appeared during installation"
    mv "$stage_source" "$source_dir"
  fi

  [[ ! -L "$state_dir" ]] || fail "managed state directory must not be a symlink"
  mkdir -p "$state_dir/storage"
  [[ ! -L "$state_dir/storage" ]] || fail "managed storage must not be a symlink"

  if [[ ! -e "$state_dir/config.toml" && ! -L "$state_dir/config.toml" ]]; then
    cp "$source_dir/config.example.toml" "$config_stage"
    chmod 600 "$config_stage"
    mv "$config_stage" "$state_dir/config.toml"
  fi
  [[ -f "$state_dir/config.toml" && ! -L "$state_dir/config.toml" ]] || fail "managed config must be a regular file"

  ensure_managed_link \
    "$source_dir/config.toml" \
    "$state_dir/config.toml" \
    '../../../.state/moneyprinterturbo/config.toml'
  ensure_managed_link \
    "$source_dir/storage" \
    "$state_dir/storage" \
    '../../../.state/moneyprinterturbo/storage'

  check_runtime "$root"
  printf 'MoneyPrinterTurbo %s is ready at %s\n' "$MPT_TAG" "$source_dir"
}

usage() {
  printf 'Usage: %s (--check|--install) [--root PATH]\n' "${0##*/}" >&2
  return 2
}

main() {
  local mode=""
  local script_dir root
  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
  root=$(cd "$script_dir/.." && pwd -P)

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --check|--install)
        [[ -z "$mode" ]] || usage
        mode=$1
        shift
        ;;
      --root)
        [[ $# -ge 2 ]] || usage
        root=$2
        shift 2
        ;;
      *)
        usage
        ;;
    esac
  done

  [[ -n "$mode" ]] || usage
  [[ -d "$root" ]] || fail "project root is missing: $root"
  root=$(cd "$root" && pwd -P)

  case "$mode" in
    --check)
      check_runtime "$root"
      printf 'MoneyPrinterTurbo %s is ready at %s\n' "$MPT_TAG" "$root/.tools/moneyprinterturbo/source"
      ;;
    --install) install_runtime "$root" ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
