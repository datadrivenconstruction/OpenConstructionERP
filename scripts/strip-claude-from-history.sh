#!/bin/bash
#
# Strip all Claude/Anthropic mentions from git commit messages.
#
# Rewrites ALL commit messages on master + main to remove:
#   - Co-Authored-By: Claude ... lines
#   - noreply@anthropic.com email trailers
#   - "Generated with [Claude Code]" markers
#   - Any "Claude Opus" / "Claude Sonnet" lines
#
# After rewriting, force-pushes master and main to origin.
#
# DESTRUCTIVE: rewrites history and changes commit SHAs. Any other
# machines with a clone of this repo will need `git fetch && git reset
# --hard origin/<branch>` to sync.
#
# Run from the project root:
#   bash scripts/strip-claude-from-history.sh
#

set -e

cd "$(git rev-parse --show-toplevel)"

echo "=== Step 1: Safety backup tag ==="
TS=$(date +%Y%m%d-%H%M%S)
git tag "backup-before-strip-claude-$TS"
echo "Tagged: backup-before-strip-claude-$TS"

echo
echo "=== Step 2: Commits that will be modified ==="
git log --all --format='%h %s' | grep -iE 'claude|anthropic|generated with' || echo "(none found in subjects — trailers only)"

echo
echo "=== Step 3: Rewriting history (this can take a minute) ==="
export FILTER_BRANCH_SQUELCH_WARNING=1

git filter-branch -f --msg-filter '
grep -v -e "Co-Authored-By: Claude" \
        -e "noreply@anthropic" \
        -e "Claude Code" \
        -e "Claude Opus" \
        -e "Claude Sonnet" \
        -e "Generated with"
' master

# If a main branch exists locally, rewrite it too
if git show-ref --verify --quiet refs/heads/main; then
  git filter-branch -f --msg-filter '
  grep -v -e "Co-Authored-By: Claude" \
          -e "noreply@anthropic" \
          -e "Claude Code" \
          -e "Claude Opus" \
          -e "Claude Sonnet" \
          -e "Generated with"
  ' main
fi

echo
echo "=== Step 4: Verify no Claude trailers remain ==="
if git log --all --format='%B' | grep -iE 'claude|anthropic|generated with'; then
  echo "WARNING: some mentions still present — inspect manually"
else
  echo "OK — all Claude/Anthropic mentions removed from commit messages"
fi

echo
echo "=== Step 5: Force-push master + main to origin ==="
git push origin master:master --force-with-lease
git push origin master:main   --force-with-lease

echo
echo "=== DONE ==="
echo "GitHub 'Top Committers' analytics will refresh within a few hours."
echo "To restore if something went wrong:"
echo "  git reset --hard backup-before-strip-claude-$TS"
