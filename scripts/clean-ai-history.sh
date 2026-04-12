#!/usr/bin/env bash
# scripts/clean-ai-history.sh
#
# Removes all AI tool traces from git commit history.
# Strips Co-authored-by trailers, Claude Code markers, Anthropic refs.
#
# REQUIRES: git-filter-repo (pip install git-filter-repo)
# USAGE:    bash scripts/clean-ai-history.sh [--dry-run] [--push]
#
# WARNING: rewrites history and changes SHA of ALL commits.
# All clones must resync after push:
#   git fetch origin && git reset --hard origin/main
#
# DataDrivenConstruction — v2.0 (uses git-filter-repo, not filter-branch)

set -euo pipefail

DRY_RUN=false
DO_PUSH=false
BRANCH="main"
BACKUP_TAG="backup-pre-clean-$(date +%Y%m%d-%H%M%S)"

for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --push)    DO_PUSH=true  ;;
    --branch=*) BRANCH="${arg#*=}" ;;
  esac
done

echo ""
echo "========================================"
echo "  AI History Cleaner v2.0"
echo "========================================"
echo ""

if ! command -v git-filter-repo &>/dev/null; then
  echo "[ERROR] git-filter-repo not installed. Install: pip install git-filter-repo"
  exit 1
fi

git rev-parse --show-toplevel &>/dev/null || { echo "[ERROR] Not a git repo"; exit 1; }
cd "$(git rev-parse --show-toplevel)"

echo "[INFO] Step 1/4: Audit"
COAUTH=$(git log --format="%B" --all | grep -iE "co-authored-by.*(claude|anthropic)" || true)
if [ -z "$COAUTH" ]; then
  echo "[OK] No AI Co-authored-by trailers found. History is clean."
  exit 0
fi
echo "[WARN] Found Co-authored-by trailers:"
echo "$COAUTH" | sort -u | head -20
echo ""

if [ "$DRY_RUN" = true ]; then
  echo "[WARN] DRY RUN -- no changes made. Remove --dry-run to execute."
  exit 0
fi

echo "[INFO] Step 2/4: Backup tag: $BACKUP_TAG"
git tag "$BACKUP_TAG"

echo "[INFO] Step 3/4: Rewriting history..."

TMPSCRIPT=$(mktemp /tmp/filter_ai_XXXXXX.py)
cat > "$TMPSCRIPT" << 'PYEOF'
import re
PATTERNS = [
    r'^\s*Co-[Aa]uthored-[Bb]y:\s+[Cc]laude.*$',
    r'^\s*Co-[Aa]uthored-[Bb]y:.*@anthropic\.com.*$',
    r'^\s*Co-[Aa]uthored-[Bb]y:.*claude\[bot\].*$',
    r'^\s*Co-[Aa]uthored-[Bb]y:.*noreply@anthropic.*$',
    r'^\s*Generated.with.*[Cc]laude.*$',
    r'^\s*Signed-off-by:.*claude.*$',
]
def clean(msg):
    lines = msg.decode('utf-8', errors='replace').split('\n')
    cleaned = [l for l in lines if not any(re.match(p, l, re.IGNORECASE) for p in PATTERNS)]
    while cleaned and cleaned[-1].strip() == '':
        cleaned.pop()
    return '\n'.join(cleaned).encode('utf-8')
commit.message = clean(commit.message)
PYEOF

git filter-repo \
  --commit-callback "$(cat "$TMPSCRIPT")" \
  --force \
  --refs "$BRANCH"

rm -f "$TMPSCRIPT"
echo "[OK] History rewritten"

echo "[INFO] Step 4/4: Verification"
REMAINING=$(git log --format="%B" --all | grep -iE "co-authored-by.*(claude|anthropic)" || true)
if [ -z "$REMAINING" ]; then
  echo "[OK] Verified -- no AI traces remain in commit messages"
else
  echo "[WARN] Some traces remain:"
  echo "$REMAINING"
fi

if [ "$DO_PUSH" = true ]; then
  echo "[INFO] Force-pushing to origin/$BRANCH..."
  git push origin "$BRANCH" --force-with-lease
  echo "[OK] Pushed. GitHub will recalculate contributors in 1-2 hours."
else
  echo ""
  echo "[INFO] Push skipped. To push:"
  echo "    git push origin $BRANCH --force-with-lease"
fi

echo ""
echo "[OK] Done. Backup tag: $BACKUP_TAG"
echo "    Restore: git reset --hard $BACKUP_TAG"
