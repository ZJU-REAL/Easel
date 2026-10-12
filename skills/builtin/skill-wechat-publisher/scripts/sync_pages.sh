#!/usr/bin/env bash
# Sync the theme-preview site into the repo-root docs/ folder that GitHub Pages
# serves ("Deploy from a branch" -> main -> /docs) for github.com/jiji262/wechat-publisher.
#
# Run this after regenerating any theme preview (see assets/theme-previews/README.md):
#
#   bash scripts/sync_pages.sh
#
# Paths are resolved from this script's own location, so cwd does not matter.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC="$REPO/assets/theme-previews"
DOCS="$REPO/docs"

[ -d "$SRC" ] || { echo "source not found: $SRC" >&2; exit 1; }

mkdir -p "$DOCS/screenshots"

# Rendered preview pages: index.html + the 15 per-theme HTML files.
cp "$SRC"/*.html "$DOCS"/
# Screenshots referenced by the overview.
cp "$SRC"/screenshots/*.webp "$DOCS/screenshots"/
# Publish files as-is (no Jekyll processing).
touch "$DOCS/.nojekyll"

echo "Synced theme previews -> $DOCS"
ls -1 "$DOCS"/*.html | sed "s#$DOCS/#  #"
