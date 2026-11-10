#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MANIFEST="custom_components/simple_inventory/manifest.json"
VERSION_FILES=("$MANIFEST")

write_version_files() {
    local ver="$1"
    local tmp

    tmp="$(mktemp)"
    sed "s/\"version\": \"[^\"]*\"/\"version\": \"${ver}\"/" "$MANIFEST" > "$tmp"
    mv "$tmp" "$MANIFEST"
}

usage() {
    cat <<'EOF'
Usage:
  release.sh <patch|minor|beta> [--yes] [--dry-run] [--remote <name>] [--branch <name>]

Behavior (based on latest stable tag vX.Y.Z):
  patch -> vX.Y.(Z+1)
  minor -> vX.(Y+1).0
  beta  -> vX.(Y+1).0bN  (N increments if existing betas for that base exist)

Steps performed:
  1. Bump version in manifest.json, commit the change (jj commit),
     and advance the release bookmark
  2. Open $EDITOR to write release notes (saved as the annotated git tag message)
  3. Create annotated tag (signed if GPG key available)
  4. Push the bookmark (jj git push) and the tag (git push) to remote
     -> GitHub Actions picks up the tag, runs tests, and creates a draft release
        using the tag annotation as the release body. Review and publish on GitHub.

Examples:
  ./release.sh patch
  ./release.sh minor --yes
  ./release.sh beta --dry-run
  ./release.sh patch --remote upstream --branch main
EOF
}

# shellcheck source=scripts/release-common.sh
source "$SCRIPT_DIR/scripts/release-common.sh"

release_main "$@"
