#!/usr/bin/env bash
# Shared release-script logic for Home Assistant integration
# and its companion frontend card. This file is kept IDENTICAL between:
#   - simple_inventory/scripts/release-common.sh
#   - simple-inventory-card/scripts/release-common.sh
# If you edit it, copy the change to the sibling repo too.
#
# Both repos are colocated jj/git repos (`.jj` + `.git`). jj is the primary
# interface for commits/bookmarks/fetch/push; tags stay plain git objects
# because `jj tag set` has no annotated/signed message support and CI reads
# the release body from the tag's message (`git tag -l --format='%(contents)'`).
# Colocated jj always keeps git HEAD pointed at the working copy's parent
# (@-), so plain `git tag` here tags whatever commit we just bumped.
#
# The caller (each repo's release.sh) must, before sourcing this file's
# functions, define:
#   usage()                    -- repo-specific --help text
#   VERSION_FILES=(...)        -- paths write_version_files touches (for messages)
#   write_version_files(ver)   -- edit the repo's version files; no git/jj calls
# then call `release_main "$@"`.

REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-master}"

die() { echo "error: $*" >&2; exit 1; }

# -------- jj helpers --------
working_copy_state() {
    jj log -r '@' --no-graph -T 'if(empty, "clean", "dirty")'
}

require_clean_tree() {
    [[ "$(working_copy_state)" == "clean" ]] \
        || die "working copy has pending changes (run 'jj commit' or 'jj new' first)"
}

fetch_all() {
    jj git fetch --remote "$REMOTE"
}

commit_id_of() {
    jj log -r "$1" --no-graph -T 'commit_id' 2>/dev/null
}

ensure_on_bookmark_up_to_date() {
    local wc_parent branch_commit remote_commit
    wc_parent="$(commit_id_of '@-')" || die "failed to resolve working copy parent"
    branch_commit="$(commit_id_of "$BRANCH")" || die "bookmark '$BRANCH' not found"
    remote_commit="$(commit_id_of "${BRANCH}@${REMOTE}")" \
        || die "remote bookmark '${BRANCH}@${REMOTE}' not found (fetch first?)"

    [[ "$wc_parent" == "$branch_commit" ]] \
        || die "working copy is not on top of bookmark '$BRANCH' (run 'jj new $BRANCH' first)"
    [[ "$branch_commit" == "$remote_commit" ]] \
        || die "'$BRANCH' is not up to date with ${REMOTE}/${BRANCH} (run 'jj git fetch' and rebase first)"
}

# -------- tag queries (plain git; tags remain git objects, see header) --------
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
    local base="$1"   # vX.Y.0
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

strip_v() { echo "${1#v}"; }

# -------- version bump --------
# Calls the caller-defined write_version_files(), then commits with jj (or
# skips cleanly if the files were already at that version) and advances the
# release bookmark to the new commit.
bump_versions() {
    local ver="$1"   # without leading 'v'

    write_version_files "$ver"

    if [[ "$(working_copy_state)" == "clean" ]]; then
        echo "Versions already at ${ver}; skipping bump commit"
        return 0
    fi

    jj commit -m "bump version to ${ver}"
    jj bookmark set "$BRANCH" -r '@-'
    echo "Bumped ${VERSION_FILES[*]} to ${ver}"
}

# -------- release notes --------
prepare_notes_file() {
    local tag="$1"
    local notes_file
    notes_file="$(mktemp /tmp/release_notes_XXXXXX)"
    cat > "$notes_file" <<EOF
# $tag

<!-- Write your release notes here. Save and close when done.
     This becomes the git tag annotation and the GitHub release body. -->

EOF
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

# -------- main driver --------
# Called by each repo's release.sh as: release_main "$@"
release_main() {
    local cmd="${1:-}"
    shift || true

    local yes=0 dry_run=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes|-y)     yes=1; shift ;;
            --dry-run|-n) dry_run=1; shift ;;
            --remote)     REMOTE="${2:-}"; [[ -n "$REMOTE" ]] || die "missing value for --remote"; shift 2 ;;
            --branch)     BRANCH="${2:-}"; [[ -n "$BRANCH" ]] || die "missing value for --branch"; shift 2 ;;
            -h|--help)    usage; exit 0 ;;
            *)            die "unknown arg: $1 (use --help)" ;;
        esac
    done

    [[ "$cmd" == "patch" || "$cmd" == "minor" || "$cmd" == "beta" ]] || { usage >&2; exit 1; }

    require_clean_tree
    fetch_all
    ensure_on_bookmark_up_to_date

    local latest_stable
    latest_stable="$(latest_stable_tag || true)"
    [[ -n "${latest_stable:-}" ]] || die "no stable tags found (expected vX.Y.Z)"

    local maj min pat
    read -r maj min pat < <(parse_stable "$latest_stable") || die "failed to parse $latest_stable"

    local proposed_tag=""
    case "$cmd" in
        patch) proposed_tag="$(mk_patch "$maj" "$min" "$pat")" ;;
        minor) proposed_tag="$(mk_minor "$maj" "$min")" ;;
        beta)
            local base
            base="$(mk_minor "$maj" "$min")"
            proposed_tag="$(mk_next_beta "$base")"
            ;;
    esac

    local version_num
    version_num="$(strip_v "$proposed_tag")"

    echo "Latest stable: $latest_stable"
    echo "Command:       $cmd"
    echo "Proposed tag:  $proposed_tag"
    echo "Branch:        $BRANCH"
    echo "Remote:        $REMOTE"
    echo "Commit:        $(git rev-parse --short HEAD)"
    echo

    tag_exists "$proposed_tag" && die "tag already exists: $proposed_tag"

    if [[ "$yes" -ne 1 ]]; then
        printf "Create & push tag %s? [y/N] " "$proposed_tag"
        read -r reply
        [[ "$reply" == "y" || "$reply" == "Y" ]] || die "aborted"
    fi

    if [[ "$dry_run" -eq 1 ]]; then
        echo "(dry-run) bump ${VERSION_FILES[*]} to ${version_num}"
        echo "(dry-run) jj commit -m 'bump version to ${version_num}'"
        echo "(dry-run) jj bookmark set $BRANCH -r @-"
        echo "(dry-run) open \${EDITOR:-vi} for release notes"
        echo "(dry-run) create tag: $proposed_tag (signed if possible, else annotated)"
        echo "(dry-run) jj git push --bookmark $BRANCH --remote $REMOTE"
        echo "(dry-run) git push $REMOTE $proposed_tag"
        exit 0
    fi

    bump_versions "$version_num"

    local notes_file
    notes_file="$(prepare_notes_file "$proposed_tag")"
    "${EDITOR:-vi}" "$notes_file"
    # Fail if only the template remains
    local content
    content="$(sed '/^<!--/d;/^[[:space:]]*$/d' "$notes_file")"
    if [[ -z "$content" ]]; then
        rm -f "$notes_file"
        die "release notes are empty; aborting"
    fi
    create_tag "$proposed_tag" "$notes_file"
    rm -f "$notes_file"

    jj git push --bookmark "$BRANCH" --remote "$REMOTE"
    git push "$REMOTE" "$proposed_tag"
    echo "Done. A draft release will be created on GitHub once CI passes."
}
