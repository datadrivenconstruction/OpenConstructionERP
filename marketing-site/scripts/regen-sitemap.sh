#!/bin/sh
# Regenerate the OpenConstructionERP marketing sitemap from the live
# docroot. Run daily by cron so new /news entries and new pages get
# picked up automatically. Logs to regen-sitemap.log next to this script.
#
# This is the exact wrapper deployed on the production VPS at
# /root/clawd/openconstructionerp-tools/regen-sitemap.sh and invoked by
# the crontab entry:
#   30 4 * * * /root/clawd/openconstructionerp-tools/regen-sitemap.sh >> /root/clawd/openconstructionerp-tools/regen-sitemap.log 2>&1
set -eu
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ROOT="/root/clawd/openconstructionerp"
SELF="/root/clawd/openconstructionerp-tools"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] regenerating sitemap..."
node "$SELF/generate-sitemap.mjs" --root "$ROOT"
