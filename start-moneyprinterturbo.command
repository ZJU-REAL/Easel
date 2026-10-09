#!/usr/bin/env bash

set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd -P)
cd "$project_root"

test -f .env
test -d skills/shared/scripts
test -x .venv/bin/python

scripts/install-moneyprinterturbo.sh --check
.venv/bin/python skills/openclaw/moneyprinterturbo-video/scripts/mpt_bridge.py configure --root "$project_root"

export MPT_WEBUI_HOST=127.0.0.1
export MPT_WEBUI_PORT=8501
source_dir="$project_root/.tools/moneyprinterturbo/source"

exec "$source_dir/webui.sh"
