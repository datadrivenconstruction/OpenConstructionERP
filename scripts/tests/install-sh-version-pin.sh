#!/usr/bin/env bash
# Guards the version pin in scripts/install.sh.
#
# WHAT THIS PROVES, AND WHAT IT DOES NOT
# The subject is pin_image_tag and unpin_image_tag, sourced from the shipped
# scripts/install.sh, run against a scratch .env. No Docker, no network, no
# install. These cases prove what the .env holds after a sequence of runs, and
# nothing about which image a real compose invocation pulls. What connects the
# two is docker-compose.quickstart.image.yml, which reads
# ${OE_IMAGE_TAG:-latest}, and the last case below asserts that the file still
# reads it, because a pin nothing consumes would make every case here vacuous.
#
# WHY IT EXISTS
# install.sh wrote a pin when a version was asked for and had no way to remove
# one. The .env outlives the run that wrote it and is read on every compose
# invocation in that directory, so the first install decided the version for
# every later one. Somebody who installed a specific version once and then ran
# the documented one-liner to upgrade pulled the version they pinned, saw the
# containers come up, and was told the installation was complete. Nothing
# anywhere reported a problem, which is the worst shape a defect can take.
#
# The asymmetry is the thing to hold on to: writing a pin and never clearing
# one is not half a feature, it is a feature that silently reverses meaning on
# the second run. So the cases are written as sequences rather than as single
# calls. A test that pinned once and read the value back would have passed
# against the broken script.
#
# HOW TO RUN
#   bash scripts/tests/install-sh-version-pin.sh
# Exit code 0 means every case passed.

set -uo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
src="$root/scripts/install.sh"
compose="$root/docker-compose.quickstart.image.yml"
[ -f "$src" ] || { echo "cannot find $src"; exit 1; }

passed=0
failed=0

assert_eq() {
    local what="$1" got="$2" want="$3"
    if [ "$got" = "$want" ]; then
        passed=$((passed + 1)); echo "  ok   $what"
    else
        failed=$((failed + 1)); echo "  FAIL $what"; echo "       wanted: $want"; echo "       got:    $got"
    fi
}

# -- The subject, sourced from the shipped script ---------------------
# Both functions plus the info helper they print through, and nothing else.
defs=$(awk '
    /^pin_image_tag\(\) \{/ {on=1}
    /^unpin_image_tag\(\) \{/ {on=1}
    on {print}
    on && /^\}$/ {on=0}
' "$src")
# Checked independently, because which one is declared first is not this
# test's business and an order-sensitive guard would fail on a tidy-up.
case "$defs$defs" in
    *"unpin_image_tag()"*"pin_image_tag()"*) : ;;
    *) echo "could not find both pin functions in $src, refusing to guess"; exit 1 ;;
esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

tag_now() {
    # What a later compose invocation in that directory would resolve to.
    if grep -q '^OE_IMAGE_TAG=' "$tmp/.env" 2>/dev/null; then
        sed -n 's/^OE_IMAGE_TAG=//p' "$tmp/.env" | tail -1
    else
        echo "latest"
    fi
}

# The branch itself, sliced rather than restated. Writing the if/else out
# here would have made every case below pass against a call site that had
# gone back to never clearing a pin: the functions would still behave, and
# the test would be measuring its own copy of the decision.
branch=$(awk '/^    if \[ "\$OE_VERSION" = "latest" \]; then/{on=1} on{print} on&&/^    fi$/{exit}' "$src")
case "$branch" in
    *unpin_image_tag*pin_image_tag*) : ;;
    *) echo "the version branch in $src no longer calls both, refusing to guess"; exit 1 ;;
esac

run_install() {
    # One run of the installer's version handling, with OE_VERSION as given.
    # Both the functions and the branch come off disk.
    OE_VERSION="$1" bash -c '
        set -euo pipefail
        info() { :; }
        cd "$1"
        '"$defs"'
        '"$branch"'
    ' _ "$tmp"
}

printf 'POSTGRES_PASSWORD=secret\nJWT_SECRET=alsosecret\n' > "$tmp/.env"

echo ""
echo "a first install with no version asked for"
run_install latest
assert_eq "resolves to latest" "$(tag_now)" "latest"

echo ""
echo "an install that asks for a version"
run_install 16.7.0
assert_eq "pins that version" "$(tag_now)" "16.7.0"

echo ""
echo "asking for a different version later"
run_install 16.8.0
assert_eq "replaces the pin rather than appending" "$(tag_now)" "16.8.0"
assert_eq "leaves exactly one pin line" "$(grep -c '^OE_IMAGE_TAG=' "$tmp/.env")" "1"

echo ""
echo "re-running the default one-liner to upgrade"
# The case the defect lived in. Before the fix this answered 16.8.0, so a
# person upgrading from a pinned install kept pulling the version they pinned
# and was told the installation had completed.
run_install 16.7.0
run_install latest
assert_eq "stops pinning and takes the latest again" "$(tag_now)" "latest"
assert_eq "removes the pin line entirely" "$(grep -c '^OE_IMAGE_TAG=' "$tmp/.env")" "0"

echo ""
echo "the secrets survive all of it"
# The reason the pin is a line in this file rather than the whole file: the
# password protects data PostgreSQL has already written, and rewriting it would
# lock the user out of their own database.
assert_eq "the database password is untouched" \
    "$(sed -n 's/^POSTGRES_PASSWORD=//p' "$tmp/.env")" "secret"
assert_eq "the token secret is untouched" \
    "$(sed -n 's/^JWT_SECRET=//p' "$tmp/.env")" "alsosecret"

echo ""
echo "clearing a pin that was never there"
printf 'POSTGRES_PASSWORD=secret\n' > "$tmp/.env"
run_install latest
assert_eq "is not an error and changes nothing" "$(cat "$tmp/.env")" "POSTGRES_PASSWORD=secret"

echo ""
echo "the pin is read by something"
# Without this the cases above would all pass over a value nothing consumes.
if grep -q 'OE_IMAGE_TAG:-latest' "$compose" 2>/dev/null; then
    passed=$((passed + 1)); echo "  ok   the image line still falls back to latest when unpinned"
else
    failed=$((failed + 1)); echo "  FAIL the compose file no longer reads OE_IMAGE_TAG with a latest fallback"
fi

echo ""
if [ "$failed" -gt 0 ]; then
    echo "$failed failed, $passed passed"
    exit 1
fi
echo "$passed passed"
exit 0
