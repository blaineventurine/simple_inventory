#!/usr/bin/env bash
set -euo pipefail

REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-master}"

MANIFEST="custom_components/simple_inventory/manifest.json"
SETUP="custom_components/simple_inventory/setup.py"

usage() {
    cat <<'EOF'
Usage:
  release.sh <patch|minor|beta> [--yes] [--dry-run] [--remote <name>] [--branch <name>]

Behavior (based on latest stable tag vX.Y.Z):
  patch -> vX.Y.(Z+1)
  minor -> vX.(Y+1).0
  beta  -> vX.(Y+1).0bN  (N increments if existing betas for that base exist)

Steps performed:
  1. Bump version in manifest.json and setup.py and commit the change
  2. Open $EDITOR to write release notes (saved as the annotated tag message)
  3. Create annotated tag (signed if GPG key available)
  4. Push commit and tag to remote
     -> GitHub Actions picks up the tag, runs tests, and creates a draft release
        using the tag annotation as the release body. Review and publish on GitHub.

Examples:
  ./release.sh patch
  ./release.sh minor --yes
  ./release.sh beta --dry-run
  ./release.sh patch --remote upstream --branch main
EOF
}

die() { echo "error: $*" >&2; exit 1; }

# -------- args --------
CMD="${1:-}"
shift || true

YES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)     YES=1; shift ;;
        --dry-run|-n) DRY_RUN=1; shift ;;
        --remote)     REMOTE="${2:-}"; [[ -n "$REMOTE" ]] || die "missing value for --remote"; shift 2 ;;
        --branch)     BRANCH="${2:-}"; [[ -n "$BRANCH" ]] || die "missing value for --branch"; shift 2 ;;
        -h|--help)    usage; exit 0 ;;
        *)            die "unknown arg: $1 (use --help)" ;;
    esac
done

[[ "$CMD" == "patch" || "$CMD" == "minor" || "$CMD" == "beta" ]] || { usage >&2; exit 1; }

# -------- git helpers --------
require_clean_tree() {
    if ! git diff --quiet || ! git diff --cached --quiet; then
        die "working tree not clean (commit/stash first)"
    fi
}

fetch_all() {
    git fetch "$REMOTE" --tags --prune
}

ensure_on_branch_up_to_date() {
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git repo"

    local current
    current="$(git rev-parse --abbrev-ref HEAD)"
    [[ "$current" == "$BRANCH" ]] || die "not on $BRANCH (currently on $current)"

    local local_sha remote_sha
    local_sha="$(git rev-parse "$BRANCH")"
    remote_sha="$(git rev-parse "$REMOTE/$BRANCH")"
    [[ "$local_sha" == "$remote_sha" ]] || die "$BRANCH not up to date with $REMOTE/$BRANCH (pull/rebase first)"
}

# Latest stable tags only (exclude betas)
latest_stable_tag() {
    git tag -l 'v[0-9]*.[0-9]*.[0-9]*' \
        | sed -E 's/^v([0-9]+)\.([0-9]+)\.([0-9]+)$/\1 \2 \3 &/' \
        | sort -k1,1n -k2,2n -k3,3n \
        | tail -n 1 \
        | awk '{print $4}'
}

parse_stable() {
    local tag="$1"
    [[ "$tag" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || return 1
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}"
}

tag_exists() {
    git rev-parse -q --verify "refs/tags/$1" >/dev/null 2>&1
}

# -------- version math --------
mk_patch() { local maj="$1" min="$2" pat="$3"; echo "v${maj}.${min}.$((pat+1))"; }
mk_minor() { local maj="$1" min="$2"; echo "v${maj}.$((min+1)).0"; }

latest_beta_for_base() {
    local base="$1"   # e.g. v0.6.0
    git tag -l "${base}b[0-9]*" \
        | sed -E "s/^${base}b([0-9]+)$/\1 &/" \
        | sort -k1,1n \
        | tail -n 1 \
        | awk '{print $2}'
}

beta_number() {
    local tag="$1" base="$2"
    [[ "$tag" =~ ^${base}b([0-9]+)$ ]] || return 1
    echo "${BASH_REMATCH[1]}"
}

mk_next_beta() {
    local base="$1"  # vX.Y.0
    local last_beta n
    last_beta="$(latest_beta_for_base "$base" || true)"
    if [[ -n "${last_beta:-}" ]]; then
        n="$(beta_number "$last_beta" "$base")"
        echo "${base}b$((n+1))"
    else
        echo "${base}b1"
    fi
}

# -------- version bump --------
strip_v() { echo "${1#v}"; }

bump_versions() {
    local ver="$1"   # without leading 'v'
    local tmp

    tmp="$(mktemp)"
    sed "s/\"version\": \"[^\"]*\"/\"version\": \"${ver}\"/" "$MANIFEST" > "$tmp"
    mv "$tmp" "$MANIFEST"

    tmp="$(mktemp)"
    sed "s/version=\"[^\"]*\"/version=\"${ver}\"/" "$SETUP" > "$tmp"
    mv "$tmp" "$SETUP"

    git add "$MANIFEST" "$SETUP"
    if git diff --cached --quiet; then
        echo "Versions already at ${ver}; skipping bump commit"
    else
        git commit -m "bump version to ${ver}"
        echo "Bumped $MANIFEST and $SETUP to ${ver}"
    fi
}

# -------- release notes --------
edit_notes() {
    local tag="$1"
    local notes_file
    notes_file="$(mktemp /tmp/release_notes_XXXXXX.md)"

    cat > "$notes_file" <<EOF
# $tag

<!-- Write your release notes here. Save and close when done.
     This becomes the git tag annotation and the GitHub release body. -->

EOF

    "${EDITOR:-vi}" "$notes_file"

    # Fail if only the template remains (no real content)
    local content
    content="$(sed '/^<!--/d;/^[[:space:]]*$/d' "$notes_file")"
    if [[ -z "$content" ]]; then
        rm -f "$notes_file"
        die "release notes are empty; aborting"
    fi

    echo "$notes_file"
}

# -------- tag creation --------
create_tag() {
    local tag="$1"
    local notes_file="$2"

    if git tag -s "$tag" -F "$notes_file" >/dev/null 2>&1; then
        echo "Created signed tag: $tag"
        return 0
    fi

    echo "Warning: tag signing failed; creating unsigned annotated tag instead: $tag" >&2
    git tag -a "$tag" -F "$notes_file"
    echo "Created annotated tag: $tag"
}

# -------- main --------
require_clean_tree
fetch_all
ensure_on_branch_up_to_date

LATEST_STABLE="$(latest_stable_tag || true)"
[[ -n "${LATEST_STABLE:-}" ]] || die "no stable tags found (expected vX.Y.Z)"

read -r MAJ MIN PAT < <(parse_stable "$LATEST_STABLE") || die "failed to parse $LATEST_STABLE"

PROPOSED_TAG=""
case "$CMD" in
    patch) PROPOSED_TAG="$(mk_patch "$MAJ" "$MIN" "$PAT")" ;;
    minor) PROPOSED_TAG="$(mk_minor "$MAJ" "$MIN")" ;;
    beta)
        BASE="$(mk_minor "$MAJ" "$MIN")"
        PROPOSED_TAG="$(mk_next_beta "$BASE")"
        ;;
esac

VERSION_NUM="$(strip_v "$PROPOSED_TAG")"

echo "Latest stable: $LATEST_STABLE"
echo "Command:       $CMD"
echo "Proposed tag:  $PROPOSED_TAG"
echo "Branch:        $BRANCH"
echo "Remote:        $REMOTE"
echo "Commit:        $(git rev-parse --short HEAD)"
echo

tag_exists "$PROPOSED_TAG" && die "tag already exists: $PROPOSED_TAG"

if [[ "$YES" -ne 1 ]]; then
    printf "Create & push tag %s? [y/N] " "$PROPOSED_TAG"
    read -r reply
    [[ "$reply" == "y" || "$reply" == "Y" ]] || die "aborted"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "(dry-run) bump $MANIFEST and $SETUP to ${VERSION_NUM}"
    echo "(dry-run) git commit -m 'bump version to ${VERSION_NUM}'"
    echo "(dry-run) open \${EDITOR:-vi} for release notes"
    echo "(dry-run) create tag: $PROPOSED_TAG (signed if possible, else annotated)"
    echo "(dry-run) git push $REMOTE $BRANCH"
    echo "(dry-run) git push $REMOTE $PROPOSED_TAG"
    exit 0
fi

bump_versions "$VERSION_NUM"

NOTES_FILE="$(edit_notes "$PROPOSED_TAG")"
create_tag "$PROPOSED_TAG" "$NOTES_FILE"
rm -f "$NOTES_FILE"

git push "$REMOTE" "$BRANCH"
git push "$REMOTE" "$PROPOSED_TAG"
echo "Done. A draft release will be created on GitHub once CI passes."
